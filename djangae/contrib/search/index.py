import uuid

from collections.abc import Iterable
from gcloudc.db import transaction

from djangae.contrib.search.document import Document
from djangae.contrib.search.fields import IntegrityError
from djangae.contrib.search import _SEARCH_QUEUE
from djangae.contrib.search.models import DocumentRecord, TokenFieldIndex, IndexStats
from djangae.tasks.deferred import defer_iteration_with_finalize

_DEFAULT_INDEX_NAME = "default"


def _destroy_record(instance):
    instance.delete()


def _finalize(*args, **kwargs):
    pass


def reindex_document(document):
    """
        Deletes old tokens, bumps the revision
        then indexes the document
    """

    try:
        record = document._record or DocumentRecord.objects.get(pk=document.id)
    except DocumentRecord.DoesNotExist:
        return

    qs = TokenFieldIndex.objects.filter(
        record_id=document.id,
        revision=document.revision
    )
    defer_iteration_with_finalize(
        qs, _destroy_record, _finalize, _shards=1, _queue=_SEARCH_QUEUE
    )

    # Generate a brand new revision ID for this document
    record.revision = uuid.uuid4()
    record.save()

    index_document(document.index_name, document)


def unindex_document(document):
    """
        Deletes a document from its index
    """

    try:
        record = document._record or DocumentRecord.objects.get(pk=document.id)
    except DocumentRecord.DoesNotExist:
        return 0

    # Find all the things to delete
    qs = TokenFieldIndex.objects.filter(
        record_id=document.id,
        revision=document.revision
    ).all()

    defer_iteration_with_finalize(
        qs, _destroy_record, _finalize, _shards=1, _queue=_SEARCH_QUEUE
    )

    record.delete()
    return 1


def index_document(index_name, document):

    assert(document.id)  # This should be a thing by now

    for field_name, field in document.get_fields().items():
        if field_name == "id":
            continue

        if not field.index:
            # Some fields are just stored, not indexed
            continue

        # Get the field value, use the default if it's not set
        value = getattr(document, field.attname, None)
        value = field.default if value is None else value
        value = field.normalize_value(value)

        # Tokenize the value, this will effectively mean lower-casing
        # removing punctuation etc. and returning a list of things
        # to index
        tokens = field.tokenize_value(value)

        if tokens is None:
            # Nothing to index
            continue

        tokens = set(tokens)  # Remove duplicates

        for token in tokens:
            token = field.clean_token(token)
            if token is None or token == '':
                continue

            # FIXME: Update occurrances
            key = TokenFieldIndex.generate_key(
                index_name, token, field.attname, document.id, document.revision
            )

            obj, _ = TokenFieldIndex.objects.get_or_create(
                pk=key,
                defaults=dict(
                    record_id=document.id,
                    revision=document.revision,
                    token=token,
                    index_stats_id=index_name,
                    field_name=field.attname
                )
            )


class Index(object):

    def __init__(self, name):

        name = name or _DEFAULT_INDEX_NAME

        self.name = name
        self.index, created = IndexStats.objects.get_or_create(
            name=name
        )

    @property
    def id(self):
        return self.index.pk if self.index else None

    def _validate_documents(self, documents):
        for document in documents:
            for field in document.get_fields().values():
                if not field.null:
                    value = getattr(document, field.attname, None)
                    if value is None:
                        raise IntegrityError()

    def add(self, document_or_documents):
        """
            Add a document, or documents to the index.

            Returns the IDs of *new* documents that have been
            added. If document_or_documents was a list, the result
            will also be a list.
        """

        added_document_ids = []

        if isinstance(document_or_documents, Document):
            was_list = False
            documents = [document_or_documents]
        else:
            was_list = True
            documents = document_or_documents[:]

        # First-pass validation
        self._validate_documents(documents)

        with transaction.atomic(independent=True):
            for document in documents:
                record = document._record

                # We go through the document fields, pull out the values that have been set
                # then we index them.
                field_data = {
                    f: getattr(document, document.get_field(f).attname)
                    for f in document.get_fields() if f != "id"
                }

                # Generate a database representation of this Document use
                # the passed ID if there is one
                record, created = DocumentRecord.objects.update_or_create(
                    pk=document.id,
                    defaults={
                        "index_stats": self.index,
                        "data": field_data
                    }
                )
                document.id = record.id
                document._record = record

                if created:
                    index_document(self.name, document)
                    added_document_ids.append(record.id)
                else:
                    # This wipes out any existing document, bumps the revision
                    # and then indexes this one
                    reindex_document(document)

        return added_document_ids if was_list else (added_document_ids[0] if added_document_ids else 0)

    def remove(self, document_or_documents):
        """
            Removes a document, or documents, from the index. Document
            instances, or document IDs are accepted.

            Returns the number of documents that were successfully removed
            from the index.
        """

        if not document_or_documents:
            return 0

        document_or_documents = (
            document_or_documents
            if isinstance(document_or_documents, Iterable)
            else [document_or_documents]
        )

        removed_count = 0

        for doc_or_id in document_or_documents:
            try:
                document = (
                    doc_or_id
                    if isinstance(doc_or_id, Document)
                    else Document(_record=DocumentRecord.objects.get(pk=doc_or_id))
                )
                removed_count += unindex_document(document)
            except DocumentRecord.DoesNotExist:
                continue

        return removed_count

    def get(self, document_id):
        raise NotImplementedError()

    def search(
        self,
        query_string,
        document_class,
        limit=1000,
        use_stemming=False,
        use_startswith=False,
        match_stopwords=True,
        match_all=False,
        order_by=None
    ):
        """
            Perform a search of the index.
            query_string: The query we're making using query syntax
            document_class: The `Document` document_class to return the results as
            limit: The max number of results to return
            use_stemming: If true, this will query for variations of the token
            use_startswith: If true, will return results where the beginning of searched tokens match
            match_stopwords: If true, stopwords included in the query will be matched.
                This will be implicitly True if use_startswith is True
            match_all: If true, only return results where all tokens are found, otherwise act as though all terms
                are separated by OR operators.
        """
        from .query import build_document_queryset

        # If we're using startswith matching, we need to include stopwords
        # regardless of what the user asked for
        if use_startswith:
            match_stopwords = True

        qs, ordered_ids = build_document_queryset(
            query_string, self,
            use_stemming=use_stemming,
            use_startswith=use_startswith,
            match_stopwords=match_stopwords,
            match_all=match_all,
        )[:limit]

        doc_instance = document_class()

        def get_field_value(field_name, record):
            field = doc_instance.get_field(field_name)
            return field.convert_from_index(record.data[field_name])

        if order_by:
            # Explicit field ordering
            qs = sorted(list(qs), key=lambda x: get_field_value(order_by, x))
        else:
            # Use ranking
            qs = sorted(list(qs), key=lambda x: ordered_ids.index(x.id))

        for record in qs:
            data = {}

            for field_name in record.data:
                data[field_name] = get_field_value(field_name, record)

            yield document_class(_record=record, **data)

    def document_count(self):
        return DocumentRecord.objects.filter(index_stats=self.index).count()
