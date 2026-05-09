from aiohttp import web

from providers import Keymanager

APP_KEY_BEARER_TOKEN = web.AppKey("bearer_token", str)
APP_KEY_KEYMANAGER = web.AppKey("keymanager", Keymanager)
