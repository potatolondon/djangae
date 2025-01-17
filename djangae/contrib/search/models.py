import uuid

from django.db import models

from gcloudc.db.models.fields.json import JSONField

from djangae.contrib.search.document import Document
from djangae.contrib.search.constants import WORD_DOCUMENT_JOIN_STRING


class DocumentRecord(models.Model):
    """
        'Document' is intentionally not a model;
        it would ruin the abstraction, and we need to
        store all kinds of data related to a Document.
        So instead, each Document has an instance of DocumentRecord
        this is the closest to a database representation of the doc
        and indeed, is where the document ID comes from.

        DocumentRecord exists to keep a reference to all token indexes
        and any stats/settings about the document (e.g. its rank).
    """
    index_stats = models.ForeignKey("IndexStats", on_delete=models.CASCADE)

    # The revision of the document. This gets changed on each reindex
    revision = models.UUIDField(default=uuid.uuid4, editable=False)

    # This is the data at the time the field was indexed so the doc
    # can be reconstructed on fetch
    data = JSONField()


class TokenFieldIndex(models.Model):
    # key should be of the format WWWW|XXXX|YYYY|ZZZZ where:
    # WWWW = index ID
    # XXXX = normalised token
    # YYYY = field_name
    # ZZZZ = document id

    # Querying for documents or fields containing the token
    # will just be a key__startswith query (effectively)
    id = models.CharField(primary_key=True, max_length=1500, default=None)

    index_stats = models.ForeignKey("IndexStats", on_delete=models.CASCADE)

    # We don't cascade delete when a document is deleted, because we clear up
    # in a background task
    record = models.ForeignKey("DocumentRecord", on_delete=models.DO_NOTHING)

    revision = models.UUIDField(default=None, editable=False, blank=False)

    token = models.CharField(max_length=500)
    field_name = models.CharField(max_length=500)

    @classmethod
    def generate_key(cls, index_name, token, field_name, document_id, revision):
        return WORD_DOCUMENT_JOIN_STRING.join(
            [str(x) for x in (index_name, token, field_name, document_id, revision)]
        )

    @classmethod
    def document_id_from_pk(cls, pk):
        """
            Given a PK in the right format, return the document ID
        """
        if pk is None:
            return None

        return int(pk.split(WORD_DOCUMENT_JOIN_STRING)[-2])

    @property
    def document_id(self):
        return self.record_id

    @property
    def document(self):
        return Document.objects.get(pk=self.document_id)

    def save(self, *args, **kwargs):
        assert (self.token.strip())  # Check we're not indexing whitespace or nothing
        assert (WORD_DOCUMENT_JOIN_STRING not in self.token)  # Don't index this special symbol

        orig_pk = self.pk

        self.pk = TokenFieldIndex.generate_key(
            self.index_stats_id, self.token, self.field_name, self.document_id, self.revision
        )
        # Just check that we didn't *change* the PK
        assert ((orig_pk is None) or orig_pk == self.pk)
        super().save(*args, **kwargs)


class IndexStats(models.Model):
    """
        This is a representation of the index
        in the datastore. Its PK is used as
        a prefix to documents and token tables
        but it's only really used itself to maintain
        statistics about the indexed data.
    """

    name = models.SlugField(max_length=100, primary_key=True)
    document_count = models.PositiveIntegerField(default=0)
