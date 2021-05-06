import os, sys
from framework import app

try:
    from googleapiclient.discovery import build
except ImportError:
    try:
        os.system("{} install google-api-python-client".format(app.config['config']['pip']))
    except:
        pass


from .plugin import blueprint, menu, plugin_load, plugin_unload, plugin_info, process_telegram_data
