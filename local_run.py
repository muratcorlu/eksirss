#!/usr/bin/env python3
# Lightweight local runner with GAE module shims to run the Flask app locally

import sys
import types
import logging


def _install_gae_shims():
    # Create package structure: google.appengine.api.urlfetch, google.appengine.ext.deferred, google.appengine.ext.ndb
    google = types.ModuleType('google')
    appengine = types.ModuleType('google.appengine')
    api = types.ModuleType('google.appengine.api')
    ext = types.ModuleType('google.appengine.ext')

    # urlfetch shim
    class _UrlFetch:
        @staticmethod
        def set_default_fetch_deadline(timeout):
            logging.info('urlfetch.set_default_fetch_deadline(%s) [shim]', timeout)

    urlfetch = types.ModuleType('google.appengine.api.urlfetch')
    urlfetch.set_default_fetch_deadline = _UrlFetch.set_default_fetch_deadline

    # deferred shim
    class _Deferred:
        @staticmethod
        def defer(func, *args, **kwargs):
            logging.info('deferred.defer(%s, args=%s, kwargs=%s) [shim - no-op]', getattr(func, '__name__', func), args, kwargs)

    deferred = types.ModuleType('google.appengine.ext.deferred')
    deferred.deferred = _Deferred

    # ndb minimal in-memory shim
    ndb = types.ModuleType('google.appengine.ext.ndb')

    _STORE = {}

    class Key:
        def __init__(self, kind, identifier):
            self._kind = kind
            self._id = identifier

        def get(self):
            return _STORE.get((self._kind, self._id))

        def id(self):
            return self._id

        def urlsafe(self):
            return str(self._id)

        def __repr__(self):
            return f"Key(kind={self._kind.__name__}, id={self._id})"

    class _Property:
        def __init__(self):
            pass

    class StringProperty(_Property):
        pass

    class JsonProperty(_Property):
        pass

    class DateTimeProperty(_Property):
        pass

    class Model:
        def __init__(self, *args, **kwargs):
            self.key = None

        @classmethod
        def query(cls, *args, **kwargs):
            # minimal iterable of keys only
            class _Q:
                def iter(self, keys_only=False):
                    for (kind, identifier), value in list(_STORE.items()):
                        if kind is cls:
                            yield Key(kind, identifier) if keys_only else value
            return _Q()

        def put(self):
            if self.key is None:
                raise RuntimeError('Model.key must be set before put() in shim')
            _STORE[(self.key.kind(), self.key.id())] = self

    def delete_multi(keys):
        for k in keys:
            _STORE.pop((k.kind(), k.id()), None)

    def KeyFactory(model_cls, identifier):
        class _KindKey(Key):
            def kind(self):
                return model_cls
        return _KindKey(model_cls, identifier)

    # Bind symbols into ndb module
    ndb.Model = Model
    ndb.StringProperty = StringProperty
    ndb.JsonProperty = JsonProperty
    ndb.DateTimeProperty = DateTimeProperty
    ndb.Key = KeyFactory
    ndb.delete_multi = delete_multi

    # Register modules in sys.modules
    sys.modules['google'] = google
    sys.modules['google.appengine'] = appengine
    sys.modules['google.appengine.api'] = api
    sys.modules['google.appengine.api.urlfetch'] = urlfetch
    sys.modules['google.appengine.ext'] = ext
    sys.modules['google.appengine.ext.deferred'] = deferred
    sys.modules['google.appengine.ext.ndb'] = ndb


def main():
    logging.basicConfig(level=logging.INFO)
    _install_gae_shims()

    # Import the Flask app from main.py
    from main import app
    app.run(host='127.0.0.1', port=5000, debug=True, use_reloader=False)


if __name__ == '__main__':
    main()


