from django.db.models import Q

from .constants import (
    STOP_WORDS,
    SPACE,
    EMPTY,
    DOUBLE_QUOTE,
    PUNCTUATION,
    SPECIAL_SYMBOLS,
    COLUMN,
)

from .models import (
    WORD_DOCUMENT_JOIN_STRING,
    DocumentRecord,
    TokenFieldIndex,
)

from .tokens import tokenize_content


# Searching for common tokens can result
# in huge result sets - so this is a hard limit
# on that result set.
#
# Unfortunately, it's not possible to rank the token
# queries to know which are more relevant so this limit
# may result in some missing results in the final resultset.

# FIXME: Come up with a solution to this. This may involve searching
# the resulting documents for tokens that had been artificially limited at the
# query phase (e.g. if a token query returns 5000 results, we then
# do some additional work on documents returned by other tokens, but
# not returned by the limited token query)
_PER_TOKEN_HARD_QUERY_LIMIT = 5000


_WORD = 'word'
_EXACT = 'exact'


def _tokenize_query_string(query_string, match_stopwords):
    """
        Returns a list of WordDocumentField keys to fetch
        based on the query_string
    """

    # We always lower case. Even Atom fields are case-insensitive
    query_string = query_string.lower()

    branches = query_string.split(" or ")

    # [(None, 'test'), (None, ''"exact thing"'), (None, 'name')]

    field_queries = []

    for branch_text in branches:
        branch_queries = []

        token = []
        in_quotes = False

        def finalize_token(token):
            SINGLE_CHAR_SYMBOL_FILTER = (PUNCTUATION | SPECIAL_SYMBOLS) - set([DOUBLE_QUOTE, COLUMN])
            final_token = "".join(token)

            if not final_token:
                token.clear()
                return

            if COLUMN in token:
                field, final_token = final_token.split(COLUMN, 1)
            else:
                field = None
            if final_token not in SINGLE_CHAR_SYMBOL_FILTER:
                branch_queries.append((field, final_token))
            token.clear()

        for i, c in enumerate(branch_text):
            if c == SPACE and not in_quotes:
                finalize_token(token)
            else:
                token.append(c)

            if c == DOUBLE_QUOTE:
                in_quotes = not in_quotes
        else:
            finalize_token(token)

        field_queries.append(branch_queries)

    # By this point, given the following query:
    # pikachu OR name:charmander OR name:"Mew Two" OR "Mr Mime"
    # we should have:
    # [[(None, "pikachu")], [("name", "charmander")], [("name", '"mew two"')], [(None, '"mr mime"')]]
    # Note that exact matches will have quotes around them

    result = []

    for branch in field_queries:
        branch_result = []

        for field, token in branch:
            if token[0] == DOUBLE_QUOTE and token[-1] == DOUBLE_QUOTE:
                branch_result.append((_EXACT, field, token.strip(DOUBLE_QUOTE)))
            else:
                branch_result.append((_WORD, field, token))

        result.append(branch_result)

    # Expand
    # For non exact matches, we may have multiple tokens separated by spaces that need
    # to be expanded into seperate entries
    for branch_result in result:
        start_length = len(branch_result)
        for i in range(start_length):
            kind, field, content = branch_result[i]
            if kind == _EXACT:
                continue

            # Split on punctuation, remove double-spaces
            content = [x.replace(SPACE, EMPTY) for x in tokenize_content(content)]

            if not content or len(content) == 1:
                # Do nothing, this was a single token
                continue
            else:
                # Replace this entry with the first token
                branch_result[i] = (kind, field, content[0])

                # Append the rest to branch_result
                for token in content[1:]:
                    branch_result.append((_WORD, field, token))

    # If we're not matching stopwords, remove them from the query
    if not match_stopwords:
        for i, branch_result in enumerate(result):
            # Remove stop-words and then tuple-ify
            result[i] = [
                (kind, field, content)
                for (kind, field, content) in branch_result
                if content and content not in STOP_WORDS
            ]

    # Now we should have
    # [
    #     [("word", None, "pikachu")], [("word", "name", "charmander")],
    #     [("exact", "name", 'mew two')], [("exact", None, 'mr mime')]
    # ]

    return result


def _append_exact_word_filters(filters, prefix, field, string):
    start = "%s%s%s" % (prefix, string, WORD_DOCUMENT_JOIN_STRING)
    end = "%s%s%s%s" % (prefix, string, WORD_DOCUMENT_JOIN_STRING, chr(0x10FFFF))

    if not field:
        filters |= Q(pk__gte=start, pk__lt=end)
    else:
        filters |= Q(pk__gte=start, pk__lt=end, field_name=field)

    return filters


def _append_startswith_word_filters(filters, prefix, field, string):
    start = "%s%s" % (prefix, string)
    end = "%s%s%s" % (prefix, string, chr(0x10FFFF))

    if not field:
        filters |= Q(pk__gte=start, pk__lt=end)
    else:
        filters |= Q(pk__gte=start, pk__lt=end, field_name=field)

    return filters


def _append_stemming_word_filters(filters, prefix, field, string):
    # FIXME: Implement
    return filters


def _calculate_score(searched, tokens):
    score = 0
    for token in tokens:
        if token in STOP_WORDS:
            score += 0.25  # 1/4 pt for stop words
        else:
            if token in searched:
                score += 1.0  # 1 point for exact match
            else:
                potentials = []
                for searched_token in searched:
                    if token.startswith(searched_token):
                        potentials.append(searched_token)

                # Find the closest match (which would be the shortest)
                best = sorted(potentials, key=lambda x: len(x))[0]

                # Just use a percentage of matched length
                score += len(best) / len(token)

    return score


def _compare_tokens(searched, found, match_all, use_startswith):
    if not match_all:
        # Match all, means match all
        return True

    if use_startswith:
        # We need to make sure that each searched token matched at least
        # one found token
        for stoken in searched:
            for ftoken in found:
                if ftoken.startswith(stoken):
                    break
            else:
                # Went through all found tokens and couldn't
                # find one that matched the searched token
                return False
        return True
    else:
        if len(searched) == len(found):
            return True
        # found len is 1, we could be dealing with an acronym
        elif len(found) == 1:
            found_tokenized = set(tokenize_content(found.pop()))
            return len(found_tokenized) == len(searched)
        return False


def _build_filters(index, branch, use_startswith, use_stemming):
    # All queries need to prefix the index
    prefix = "%s%s" % (str(index.id), WORD_DOCUMENT_JOIN_STRING)
    filters = Q()

    for kind, field, string in branch:
        if kind == _WORD:
            filters = _append_exact_word_filters(filters, prefix, field, string)
            if use_startswith:
                filters = _append_startswith_word_filters(
                    filters, prefix, field, string
                )

            if use_stemming:
                filters = _append_stemming_word_filters(
                    filters, prefix, field, string,
                )
        else:
            raise NotImplementedError("Need to implement exact matching")

    return filters


def build_document_queryset(
    query_string, index,
    use_stemming=False,
    use_startswith=False,
    match_stopwords=False,
    match_all=False,
):

    """
        Returns a tuple of (queryset, doc_ids) where doc_ids is the ordered
        set of document ids based on simple ranking rules.
    """

    assert (index.id)

    tokenization = _tokenize_query_string(query_string, match_stopwords=match_stopwords)
    if not tokenization:
        return DocumentRecord.objects.none()

    if not match_all:
        # If match_all is false, we split the branches into a branch per token
        split_branches = []
        for branch in tokenization:
            for token in branch:
                split_branches.append([token])
        tokenization = split_branches

    # We now need to gather document IDs, for each branch we need to
    # look for matching tokens in a single query, then post-process them
    # to only fetch documents that match all of them.
    doc_scores = {}
    for branch in tokenization:
        tokens = set([x[-1] for x in branch])

        filters = _build_filters(index, branch, use_startswith, use_stemming)

        keys = TokenFieldIndex.objects.filter(
            filters
        ).values_list("pk", flat=True)[:_PER_TOKEN_HARD_QUERY_LIMIT]

        doc_results = {}

        for pk in keys:
            doc_id = TokenFieldIndex.document_id_from_pk(pk)
            token = pk.split("|")[1]
            doc_results.setdefault(doc_id, set()).add(token)

        for doc_id, found_tokens in doc_results.items():
            if _compare_tokens(tokens, found_tokens, match_all, use_startswith):
                doc_scores[doc_id] = doc_scores.get(doc_id, 0) + _calculate_score(
                    tokens, found_tokens
                )

    document_ids = [
        x[0] for x in sorted(doc_scores.items(), key=lambda x: -x[1])
    ]
    results = DocumentRecord.objects.filter(pk__in=document_ids)
    return results, document_ids
