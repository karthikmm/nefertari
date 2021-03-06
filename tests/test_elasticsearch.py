import logging

import pytest
from mock import Mock, patch, call
from elasticsearch.exceptions import TransportError

from nefertari import elasticsearch as es
from nefertari.json_httpexceptions import JHTTPBadRequest, JHTTPNotFound
from nefertari.utils import dictset


class TestESHttpConnection(object):

    @patch('nefertari.elasticsearch.log')
    def test_perform_request_debug(self, mock_log):
        mock_log.level = logging.DEBUG
        conn = es.ESHttpConnection()
        conn.pool = Mock()
        conn.pool.urlopen.return_value = Mock(data='foo', status=200)
        conn.perform_request('POST', 'http://localhost:9200')
        mock_log.debug.assert_called_once_with(
            "('POST', 'http://localhost:9200')")
        conn.perform_request('POST', 'http://localhost:9200'*200)
        assert mock_log.debug.call_count == 2

    def test_perform_request_exception(self):
        conn = es.ESHttpConnection()
        conn.pool = Mock()
        conn.pool.urlopen.side_effect = TransportError('N/A', '')
        with pytest.raises(JHTTPBadRequest):
            conn.perform_request('POST', 'http://localhost:9200')

    @patch('nefertari.elasticsearch.log')
    def test_perform_request_no_index(self, mock_log):
        mock_log.level = logging.DEBUG
        mock_log.debug.side_effect = TransportError(404, '')
        conn = es.ESHttpConnection()
        with pytest.raises(es.IndexNotFoundException):
            conn.perform_request('POST', 'http://localhost:9200')


class TestHelperFunctions(object):
    @patch('nefertari.elasticsearch.ES')
    def test_includeme(self, mock_es):
        config = Mock()
        config.registry.settings = {'foo': 'bar'}
        es.includeme(config)
        mock_es.setup.assert_called_once_with({'foo': 'bar'})

    def test_apply_sort(self):
        assert es.apply_sort('+foo,-bar ,zoo') == 'foo:asc,bar:desc,zoo:asc'

    def test_apply_sort_empty(self):
        assert es.apply_sort('') == ''

    def test_build_terms(self):
        terms = es.build_terms('foo', [1, 2, 3])
        assert terms == 'foo:1 OR foo:2 OR foo:3'

    def test_build_terms_custom_operator(self):
        terms = es.build_terms('foo', [1, 2, 3], operator='AND')
        assert terms == 'foo:1 AND foo:2 AND foo:3'

    def test_build_qs(self):
        qs = es.build_qs(dictset({'foo': 1, 'bar': '_all', 'zoo': 2}))
        assert qs == 'foo:1 AND zoo:2'

    def test_build_list(self):
        qs = es.build_qs(dictset({'foo': [1, 2], 'zoo': 3}))
        assert qs == 'foo:1 OR foo:2 AND zoo:3'

    def test_build_dunder_key(self):
        qs = es.build_qs(dictset({'foo': [1, 2], '__zoo__': 3}))
        assert qs == 'foo:1 OR foo:2'

    def test_build_raw_terms(self):
        qs = es.build_qs(dictset({'foo': [1, 2]}), _raw_terms=' AND qoo:1')
        assert qs == 'foo:1 OR foo:2 AND qoo:1'

    def test_build_operator(self):
        qs = es.build_qs(dictset({'foo': 1, 'qoo': 2}), operator='OR')
        assert qs == 'qoo:2 OR foo:1'

    def test_es_docs(self):
        assert issubclass(es._ESDocs, list)
        docs = es._ESDocs()
        assert docs._total == 0
        assert docs._start == 0

    @patch('nefertari.elasticsearch.ES')
    def test_bulk_body(self, mock_es):
        es._bulk_body('foo')
        mock_es.api.bulk.assert_called_once_with(body='foo')


class TestES(object):

    @patch('nefertari.elasticsearch.ES.settings')
    def test_init(self, mock_set):
        obj = es.ES(source='Foo')
        assert obj.index_name == mock_set.index_name
        assert obj.doc_type == 'foo'
        assert obj.chunk_size == 100
        obj = es.ES(source='Foo', index_name='a', chunk_size=2)
        assert obj.index_name == 'a'
        assert obj.doc_type == 'foo'
        assert obj.chunk_size == 2

    def test_src2type(self):
        assert es.ES.src2type('FooO') == 'fooo'

    @patch('nefertari.elasticsearch.engine')
    @patch('nefertari.elasticsearch.elasticsearch')
    def test_setup(self, mock_es, mock_engine):
        settings = dictset({
            'elasticsearch.hosts': '127.0.0.1:8080,127.0.0.2:8090',
            'elasticsearch.sniff': 'true',
        })
        es.ES.setup(settings)
        mock_es.Elasticsearch.assert_called_once_with(
            hosts=[{'host': '127.0.0.1', 'port': '8080'},
                   {'host': '127.0.0.2', 'port': '8090'}],
            serializer=mock_engine.ESJSONSerializer(),
            connection_class=es.ESHttpConnection,
            sniff_on_start=True,
            sniff_on_connection_fail=True
        )
        assert es.ES.api == mock_es.Elasticsearch()

    @patch('nefertari.elasticsearch.engine')
    @patch('nefertari.elasticsearch.elasticsearch')
    def test_setup_no_settings(self, mock_es, mock_engine):
        settings = dictset({})
        with pytest.raises(Exception) as ex:
            es.ES.setup(settings)
        assert 'Bad or missing settings for elasticsearch' in str(ex.value)
        assert not mock_es.Elasticsearch.called

    def test_process_chunks(self):
        obj = es.ES('Foo', 'foondex')
        operation = Mock()
        documents = [1, 2, 3, 4, 5]
        obj.process_chunks(documents, operation, chunk_size=100)
        operation.assert_called_once_with([1, 2, 3, 4, 5])

    def test_process_chunks_multiple(self):
        obj = es.ES('Foo', 'foondex')
        operation = Mock()
        documents = [1, 2, 3, 4, 5]
        obj.process_chunks(documents, operation, chunk_size=3)
        operation.assert_has_calls([call([1, 2, 3]), call([4, 5])])

    def test_process_chunks_no_docs(self):
        obj = es.ES('Foo', 'foondex')
        operation = Mock()
        obj.process_chunks([], operation, chunk_size=3)
        assert not operation.called

    def test_prep_bulk_documents_not_dict(self):
        obj = es.ES('Foo', 'foondex')
        with pytest.raises(ValueError) as ex:
            obj.prep_bulk_documents('', 'q')
        assert str(ex.value) == 'Document type must be `dict` not a `str`'

    def test_prep_bulk_documents(self):
        obj = es.ES('Foo', 'foondex')
        docs = [
            {'_type': 'Story', 'id': 'story1'},
            {'_type': 'Story', 'id': 'story2'},
        ]
        prepared = obj.prep_bulk_documents('myaction', docs)
        assert len(prepared) == 2
        doc1meta, doc1 = prepared[0]
        assert doc1meta.keys() == ['myaction']
        assert doc1meta['myaction'].keys() == [
            'action', '_type', '_id', '_index']
        assert doc1 == {'_type': 'Story', 'id': 'story1'}
        assert doc1meta['myaction']['action'] == 'myaction'
        assert doc1meta['myaction']['_index'] == 'foondex'
        assert doc1meta['myaction']['_type'] == 'story'
        assert doc1meta['myaction']['_id'] == 'story1'

    def test_prep_bulk_documents_no_type(self):
        obj = es.ES('Foo', 'foondex')
        docs = [
            {'id': 'story2'},
        ]
        prepared = obj.prep_bulk_documents('myaction', docs)
        assert len(prepared) == 1
        doc2meta, doc2 = prepared[0]
        assert doc2meta.keys() == ['myaction']
        assert doc2meta['myaction'].keys() == [
            'action', '_type', '_id', '_index']
        assert doc2 == {'id': 'story2'}
        assert doc2meta['myaction']['action'] == 'myaction'
        assert doc2meta['myaction']['_index'] == 'foondex'
        assert doc2meta['myaction']['_type'] == 'foo'
        assert doc2meta['myaction']['_id'] == 'story2'

    def test_bulk_no_docs(self):
        obj = es.ES('Foo', 'foondex')
        assert obj._bulk('myaction', []) is None

    @patch('nefertari.elasticsearch.ES.prep_bulk_documents')
    @patch('nefertari.elasticsearch.ES.process_chunks')
    def test_bulk(self, mock_proc, mock_prep):
        obj = es.ES('Foo', 'foondex', chunk_size=1)
        docs = [
            [{'delete': {'action': 'delete', '_id': 'story1'}},
             {'_type': 'Story', 'id': 'story1', 'timestamp': 1}],
            [{'index': {'action': 'index', '_id': 'story2'}},
             {'_type': 'Story', 'id': 'story2', 'timestamp': 2}],
        ]
        mock_prep.return_value = docs
        obj._bulk('myaction', docs)
        mock_prep.assert_called_once_with('myaction', docs)
        mock_proc.assert_called_once_with(
            documents=[
                {'delete': {'action': 'delete', '_id': 'story1'}},
                {'index': {'action': 'index', '_id': 'story2'},
                 '_timestamp': 2},
                {'_type': 'Story', 'id': 'story2', 'timestamp': 2},
            ],
            operation=es._bulk_body,
            chunk_size=2
        )

    @patch('nefertari.elasticsearch.ES.prep_bulk_documents')
    @patch('nefertari.elasticsearch.ES.process_chunks')
    def test_bulk_no_prepared_docs(self, mock_proc, mock_prep):
        obj = es.ES('Foo', 'foondex', chunk_size=1)
        mock_prep.return_value = []
        obj._bulk('myaction', ['a'], chunk_size=4)
        mock_prep.assert_called_once_with('myaction', ['a'])
        assert not mock_proc.called

    @patch('nefertari.elasticsearch.ES._bulk')
    def test_index(self, mock_bulk):
        obj = es.ES('Foo', 'foondex')
        obj.index(['a'], chunk_size=4)
        mock_bulk.assert_called_once_with('index', ['a'], 4)

    @patch('nefertari.elasticsearch.ES._bulk')
    def test_delete(self, mock_bulk):
        obj = es.ES('Foo', 'foondex')
        obj.delete(ids=[1, 2])
        mock_bulk.assert_called_once_with(
            'delete', [{'id': 1, '_type': 'foo'}, {'id': 2, '_type': 'foo'}])

    @patch('nefertari.elasticsearch.ES._bulk')
    def test_delete_single_obj(self, mock_bulk):
        obj = es.ES('Foo', 'foondex')
        obj.delete(ids=1)
        mock_bulk.assert_called_once_with(
            'delete', [{'id': 1, '_type': 'foo'}])

    @patch('nefertari.elasticsearch.ES._bulk')
    @patch('nefertari.elasticsearch.ES.api.mget')
    def test_index_missing_documents(self, mock_mget, mock_bulk):
        obj = es.ES('Foo', 'foondex')
        documents = [
            {'id': 1, 'name': 'foo'},
            {'id': 2, 'name': 'bar'},
            {'id': 3, 'name': 'baz'},
        ]
        mock_mget.return_value = {'docs': [
            {'_id': '1', 'name': 'foo', 'found': False},
            {'_id': '2', 'name': 'bar', 'found': True},
            {'_id': '3', 'name': 'baz'},
        ]}
        obj.index_missing_documents(documents, 10)
        mock_mget.assert_called_once_with(
            index='foondex',
            doc_type='foo',
            fields=['_id'],
            body={'ids': [1, 2, 3]}
        )
        mock_bulk.assert_called_once_with(
            'index', [{'id': 1, 'name': 'foo'}, {'id': 3, 'name': 'baz'}], 10)

    @patch('nefertari.elasticsearch.ES._bulk')
    @patch('nefertari.elasticsearch.ES.api.mget')
    def test_index_missing_documents_no_index(self, mock_mget, mock_bulk):
        obj = es.ES('Foo', 'foondex')
        documents = [
            {'id': 1, 'name': 'foo'},
        ]
        mock_mget.side_effect = es.IndexNotFoundException()
        obj.index_missing_documents(documents, 10)
        mock_mget.assert_called_once_with(
            index='foondex',
            doc_type='foo',
            fields=['_id'],
            body={'ids': [1]}
        )
        mock_bulk.assert_called_once_with(
            'index', [{'id': 1, 'name': 'foo'}], 10)

    @patch('nefertari.elasticsearch.ES._bulk')
    @patch('nefertari.elasticsearch.ES.api.mget')
    def test_index_missing_documents_no_docs_passed(self, mock_mget, mock_bulk):
        obj = es.ES('Foo', 'foondex')
        assert obj.index_missing_documents([], 10) is None
        assert not mock_mget.called
        assert not mock_bulk.called

    @patch('nefertari.elasticsearch.ES._bulk')
    @patch('nefertari.elasticsearch.ES.api.mget')
    def test_index_missing_documents_all_docs_found(self, mock_mget, mock_bulk):
        obj = es.ES('Foo', 'foondex')
        documents = [
            {'id': 1, 'name': 'foo'},
        ]
        mock_mget.return_value = {'docs': [
            {'_id': '1', 'name': 'foo', 'found': True},
        ]}
        obj.index_missing_documents(documents, 10)
        mock_mget.assert_called_once_with(
            index='foondex',
            doc_type='foo',
            fields=['_id'],
            body={'ids': [1]}
        )
        assert not mock_bulk.called

    def test_get_by_ids_no_ids(self):
        obj = es.ES('Foo', 'foondex')
        docs = obj.get_by_ids([])
        assert isinstance(docs, es._ESDocs)
        assert len(docs) == 0

    @patch('nefertari.elasticsearch.ES.api.mget')
    def test_get_by_ids(self, mock_mget):
        obj = es.ES('Foo', 'foondex')
        documents = [{'_id': 1, '_type': 'Story'}]
        mock_mget.return_value = {
            'docs': [{
                '_type': 'foo',
                '_id': 1,
                '_source': {'_id': 1, '_type': 'Story', 'name': 'bar'},
                'fields': {'name': 'bar'}
            }]
        }
        docs = obj.get_by_ids(documents, _page=0)
        mock_mget.assert_called_once_with(
            body={'docs': [{'_index': 'foondex', '_type': 'story', '_id': 1}]}
        )
        assert len(docs) == 1
        assert docs[0]._id == 1
        assert docs[0].name == 'bar'
        assert docs[0]._type == 'Story'
        assert docs._nefertari_meta['total'] == 1
        assert docs._nefertari_meta['start'] == 0
        assert docs._nefertari_meta['fields'] == []

    @patch('nefertari.elasticsearch.ES.api.mget')
    def test_get_by_ids_fields(self, mock_mget):
        obj = es.ES('Foo', 'foondex')
        documents = [{'_id': 1, '_type': 'Story'}]
        mock_mget.return_value = {
            'docs': [{
                '_type': 'foo',
                '_id': 1,
                '_source': {'_id': 1, '_type': 'Story', 'name': 'bar'},
                'fields': {'name': 'bar'}
            }]
        }
        docs = obj.get_by_ids(documents, _limit=1, _fields=['name'])
        mock_mget.assert_called_once_with(
            body={'docs': [{'_index': 'foondex', '_type': 'story', '_id': 1}]},
            fields=['name']
        )
        assert len(docs) == 1
        assert not hasattr(docs[0], '_id')
        assert not hasattr(docs[0], '_type')
        assert docs[0].name == 'bar'
        assert docs._nefertari_meta['total'] == 1
        assert docs._nefertari_meta['start'] == 0
        assert docs._nefertari_meta['fields'] == ['name']

    @patch('nefertari.elasticsearch.ES.api.mget')
    def test_get_by_ids_no_index_raise(self, mock_mget):
        obj = es.ES('Foo', 'foondex')
        documents = [{'_id': 1, '_type': 'Story'}]
        mock_mget.side_effect = es.IndexNotFoundException()
        with pytest.raises(JHTTPNotFound) as ex:
            obj.get_by_ids(documents, __raise_on_empty=True)
        assert 'resource not found (Index does not exist)' in str(ex.value)

    @patch('nefertari.elasticsearch.ES.api.mget')
    def test_get_by_ids_no_index_not_raise(self, mock_mget):
        obj = es.ES('Foo', 'foondex')
        documents = [{'_id': 1, '_type': 'Story'}]
        mock_mget.side_effect = es.IndexNotFoundException()
        try:
            docs = obj.get_by_ids(documents, __raise_on_empty=False)
        except JHTTPNotFound:
            raise Exception('Unexpected error')
        assert len(docs) == 0

    @patch('nefertari.elasticsearch.ES.api.mget')
    def test_get_by_ids_not_found_raise(self, mock_mget):
        obj = es.ES('Foo', 'foondex')
        documents = [{'_id': 1, '_type': 'Story'}]
        mock_mget.return_value = {'docs': [{'_type': 'foo', '_id': 1}]}
        with pytest.raises(JHTTPNotFound):
            obj.get_by_ids(documents, __raise_on_empty=True)

    @patch('nefertari.elasticsearch.ES.api.mget')
    def test_get_by_ids_not_found_not_raise(self, mock_mget):
        obj = es.ES('Foo', 'foondex')
        documents = [{'_id': 1, '_type': 'Story'}]
        mock_mget.return_value = {'docs': [{'_type': 'foo', '_id': 1}]}
        try:
            docs = obj.get_by_ids(documents, __raise_on_empty=False)
        except JHTTPNotFound:
            raise Exception('Unexpected error')
        assert len(docs) == 0

    def test_build_search_params_no_body(self):
        obj = es.ES('Foo', 'foondex')
        params = obj.build_search_params(
            {'foo': 1, 'zoo': 2, '_raw_terms': ' AND q:5', '_limit': 10}
        )
        assert params.keys() == ['body', 'doc_type', 'from_', 'size', 'index']
        assert params['body'] == {
            'query': {'query_string': {'query': 'foo:1 AND zoo:2 AND q:5'}}}
        assert params['index'] == 'foondex'
        assert params['doc_type'] == 'foo'

    def test_build_search_params_no_body_no_qs(self):
        obj = es.ES('Foo', 'foondex')
        params = obj.build_search_params({'_limit': 10})
        assert params.keys() == ['body', 'doc_type', 'from_', 'size', 'index']
        assert params['body'] == {'query': {'match_all': {}}}
        assert params['index'] == 'foondex'
        assert params['doc_type'] == 'foo'

    def test_build_search_params_no_limit(self):
        obj = es.ES('Foo', 'foondex')
        with pytest.raises(JHTTPBadRequest) as ex:
            obj.build_search_params({'foo': 1})
        assert str(ex.value) == 'Missing _limit'

    def test_build_search_params_sort(self):
        obj = es.ES('Foo', 'foondex')
        params = obj.build_search_params({
            'foo': 1, '_sort': '+a,-b,c', '_limit': 10})
        assert params.keys() == [
            'body', 'doc_type', 'index', 'sort', 'from_', 'size']
        assert params['body'] == {
            'query': {'query_string': {'query': 'foo:1'}}}
        assert params['index'] == 'foondex'
        assert params['doc_type'] == 'foo'
        assert params['sort'] == 'a:asc,b:desc,c:asc'

    def test_build_search_params_fields(self):
        obj = es.ES('Foo', 'foondex')
        params = obj.build_search_params({
            'foo': 1, '_fields': ['a'], '_limit': 10})
        assert params.keys() == [
            'body', 'doc_type', 'index', 'fields', 'from_', 'size']
        assert params['body'] == {
            'query': {'query_string': {'query': 'foo:1'}}}
        assert params['index'] == 'foondex'
        assert params['doc_type'] == 'foo'
        assert params['fields'] == ['a']

    def test_build_search_params_search_fields(self):
        obj = es.ES('Foo', 'foondex')
        params = obj.build_search_params({
            'foo': 1, '_search_fields': 'a,b', '_limit': 10})
        assert params.keys() == ['body', 'doc_type', 'from_', 'size', 'index']
        assert params['body'] == {'query': {'query_string': {
            'fields': ['b^1', 'a^2'],
            'query': 'foo:1'}}}
        assert params['index'] == 'foondex'
        assert params['doc_type'] == 'foo'

    @patch('nefertari.elasticsearch.ES.api.count')
    def test_do_count(self, mock_count):
        obj = es.ES('Foo', 'foondex')
        mock_count.return_value = {'count': 123}
        val = obj.do_count(
            {'foo': 1, 'size': 2, 'from_': 0, 'sort': 'foo:asc'})
        assert val == 123
        mock_count.assert_called_once_with(foo=1)

    @patch('nefertari.elasticsearch.ES.api.count')
    def test_do_count_no_index(self, mock_count):
        obj = es.ES('Foo', 'foondex')
        mock_count.side_effect = es.IndexNotFoundException()
        val = obj.do_count(
            {'foo': 1, 'size': 2, 'from_': 0, 'sort': 'foo:asc'})
        assert val == 0
        mock_count.assert_called_once_with(foo=1)

    @patch('nefertari.elasticsearch.ES.build_search_params')
    @patch('nefertari.elasticsearch.ES.do_count')
    def test_get_collection_count_without_body(self, mock_count, mock_build):
        obj = es.ES('Foo', 'foondex')
        mock_build.return_value = {'foo': 'bar'}
        obj.get_collection(_count=True, foo=1)
        mock_count.assert_called_once_with({'foo': 'bar'})
        mock_build.assert_called_once_with({'_count': True, 'foo': 1})

    @patch('nefertari.elasticsearch.ES.build_search_params')
    @patch('nefertari.elasticsearch.ES.do_count')
    def test_get_collection_count_with_body(self, mock_count, mock_build):
        obj = es.ES('Foo', 'foondex')
        obj.get_collection(_count=True, foo=1, body={'foo': 'bar'})
        mock_count.assert_called_once_with(
            {'body': {'foo': 'bar'}, '_count': True, 'foo': 1})
        assert not mock_build.called

    @patch('nefertari.elasticsearch.ES.api.search')
    def test_get_collection_fields(self, mock_search):
        obj = es.ES('Foo', 'foondex')
        mock_search.return_value = {
            'hits': {
                'hits': [{'fields': {'foo': 'bar', 'id': 1}, '_score': 2}],
                'total': 4,
            },
            'took': 2.8,
        }
        docs = obj.get_collection(
            fields=['foo'], body={'foo': 'bar'}, from_=0)
        mock_search.assert_called_once_with(body={'foo': 'bar'}, from_=0)
        assert len(docs) == 1
        assert docs[0].id == 1
        assert docs[0]._score == 2
        assert docs[0].foo == 'bar'
        assert docs._nefertari_meta['total'] == 4
        assert docs._nefertari_meta['start'] == 0
        assert docs._nefertari_meta['fields'] == ['foo']
        assert docs._nefertari_meta['took'] == 2.8

    @patch('nefertari.elasticsearch.ES.api.search')
    def test_get_collection_source(self, mock_search):
        obj = es.ES('Foo', 'foondex')
        mock_search.return_value = {
            'hits': {
                'hits': [{'_source': {'foo': 'bar', 'id': 1}, '_score': 2}],
                'total': 4,
            },
            'took': 2.8,
        }
        docs = obj.get_collection(body={'foo': 'bar'}, from_=0)
        mock_search.assert_called_once_with(body={'foo': 'bar'}, from_=0)
        assert len(docs) == 1
        assert docs[0].id == 1
        assert docs[0]._score == 2
        assert docs[0].foo == 'bar'
        assert docs._nefertari_meta['total'] == 4
        assert docs._nefertari_meta['start'] == 0
        assert docs._nefertari_meta['fields'] == ''
        assert docs._nefertari_meta['took'] == 2.8

    @patch('nefertari.elasticsearch.ES.api.search')
    def test_get_collection_no_index_raise(self, mock_search):
        obj = es.ES('Foo', 'foondex')
        mock_search.side_effect = es.IndexNotFoundException()
        with pytest.raises(JHTTPNotFound) as ex:
            obj.get_collection(
                body={'foo': 'bar'}, __raise_on_empty=True,
                from_=0)
        assert 'resource not found (Index does not exist)' in str(ex.value)

    @patch('nefertari.elasticsearch.ES.api.search')
    def test_get_collection_no_index_not_raise(self, mock_search):
        obj = es.ES('Foo', 'foondex')
        mock_search.side_effect = es.IndexNotFoundException()
        try:
            docs = obj.get_collection(
                body={'foo': 'bar'}, __raise_on_empty=False,
                from_=0)
        except JHTTPNotFound:
            raise Exception('Unexpected error')
        assert len(docs) == 0

    @patch('nefertari.elasticsearch.ES.api.search')
    def test_get_collection_not_found_raise(self, mock_search):
        obj = es.ES('Foo', 'foondex')
        mock_search.return_value = {
            'hits': {
                'hits': [],
                'total': 4,
            },
            'took': 2.8,
        }
        with pytest.raises(JHTTPNotFound):
            obj.get_collection(
                body={'foo': 'bar'}, __raise_on_empty=True,
                from_=0)

    @patch('nefertari.elasticsearch.ES.api.search')
    def test_get_collection_not_found_not_raise(self, mock_search):
        obj = es.ES('Foo', 'foondex')
        mock_search.return_value = {
            'hits': {
                'hits': [],
                'total': 4,
            },
            'took': 2.8,
        }
        try:
            docs = obj.get_collection(
                body={'foo': 'bar'}, __raise_on_empty=False,
                from_=0)
        except JHTTPNotFound:
            raise Exception('Unexpected error')
        assert len(docs) == 0

    @patch('nefertari.elasticsearch.ES.api.get_source')
    def test_get_resource(self, mock_get):
        obj = es.ES('Foo', 'foondex')
        mock_get.return_value = {'foo': 'bar', 'id': 4, '_type': 'Story'}
        story = obj.get_resource(name='foo')
        assert story.id == 4
        assert story.foo == 'bar'
        mock_get.assert_called_once_with(
            name='foo', index='foondex', doc_type='foo', ignore=404)

    @patch('nefertari.elasticsearch.ES.api.get_source')
    def test_get_resource_no_index_raise(self, mock_get):
        obj = es.ES('Foo', 'foondex')
        mock_get.side_effect = es.IndexNotFoundException()
        with pytest.raises(JHTTPNotFound) as ex:
            obj.get_resource(name='foo')
        assert 'resource not found (Index does not exist)' in str(ex.value)

    @patch('nefertari.elasticsearch.ES.api.get_source')
    def test_get_resource_no_index_not_raise(self, mock_get):
        obj = es.ES('Foo', 'foondex')
        mock_get.side_effect = es.IndexNotFoundException()
        try:
            obj.get_resource(name='foo', __raise_on_empty=False)
        except JHTTPNotFound:
            raise Exception('Unexpected error')

    @patch('nefertari.elasticsearch.ES.api.get_source')
    def test_get_resource_not_found_raise(self, mock_get):
        obj = es.ES('Foo', 'foondex')
        mock_get.return_value = {}
        with pytest.raises(JHTTPNotFound):
            obj.get_resource(name='foo')

    @patch('nefertari.elasticsearch.ES.api.get_source')
    def test_get_resource_not_found_not_raise(self, mock_get):
        obj = es.ES('Foo', 'foondex')
        mock_get.return_value = {}
        try:
            obj.get_resource(name='foo', __raise_on_empty=False)
        except JHTTPNotFound:
            raise Exception('Unexpected error')

    @patch('nefertari.elasticsearch.ES.get_resource')
    def test_get(self, mock_get):
        obj = es.ES('Foo', 'foondex')
        obj.get(__raise=True, foo=1)
        mock_get.assert_called_once_with(__raise_on_empty=True, foo=1)

    @patch('nefertari.elasticsearch.ES.settings')
    @patch('nefertari.elasticsearch.ES.index')
    def test_index_refs(self, mock_ind, mock_settings):
        class Foo(object):
            _index_enabled = True

        docs = [Foo()]
        db_obj = Mock()
        db_obj.get_reference_documents.return_value = [(Foo, docs)]
        mock_settings.index_name = 'foo'
        es.ES.index_refs(db_obj)
        mock_ind.assert_called_once_with(docs)

    @patch('nefertari.elasticsearch.ES.settings')
    @patch('nefertari.elasticsearch.ES.index')
    def test_index_refs_index_disabled(self, mock_ind, mock_settings):
        class Foo(object):
            _index_enabled = False

        docs = [Foo()]
        db_obj = Mock()
        db_obj.get_reference_documents.return_value = [(Foo, docs)]
        mock_settings.index_name = 'foo'
        es.ES.index_refs(db_obj)
        assert not mock_ind.called
