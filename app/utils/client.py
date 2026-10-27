import re
import uuid

from flask import g, request

COOKIE_NAME = 'oc_client'
COOKIE_MAX_AGE = 2 * 365 * 24 * 3600
VALID_ID = re.compile(r'^[0-9a-f]{32}$')


def init_client_id(app):
    @app.before_request
    def load_client_id():
        value = request.cookies.get(COOKIE_NAME, '')
        g.client_id_is_new = not VALID_ID.match(value)
        g.client_id = uuid.uuid4().hex if g.client_id_is_new else value

    @app.after_request
    def store_client_id(response):
        if getattr(g, 'client_id_is_new', False):
            response.set_cookie(COOKIE_NAME, g.client_id, max_age=COOKIE_MAX_AGE, httponly=True, samesite='Lax')
        return response


def client_id():
    return getattr(g, 'client_id', None) or 'anonymous'
