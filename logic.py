# -*- coding: utf-8 -*-
#########################################################
# python
import os
import traceback
import time
import threading
import platform
# third-party

# sjva 공용
from framework import db, scheduler, path_app_root, path_data
from framework.job import Job
from framework.util import Util

# 패키지
from .plugin import logger, package_name
from .model import ModelSetting
#########################################################


class Logic(object):
    db_default = { 
        'db_version' : '1',
        'path_credentials' : os.path.join(path_data, package_name, 'credentials.json'),
        'path_accounts' : os.path.join(path_data, package_name, 'accounts'),
        'path_token' : os.path.join(path_data, package_name, 'token.pickle'),
        'gclone_path' : os.path.join(os.path.dirname(__file__), 'bin', 'gclone'),
        'gclone_config_path' : os.path.join(path_data, package_name, 'gclone.conf'),
        'gclone_queue_list' : '',
        'gclone_fix_option' : '--log-level INFO --stats 1s',
        'gclone_user_option' : '--drive-server-side-across-configs --tpslimit 3 --transfers 3 --create-empty-src-dirs --ignore-existing --size-only --disable ListR',
        'gclone_default_folderid' : '',
    }

    @staticmethod
    def db_init():
        try:
            for key, value in Logic.db_default.items():
                if db.session.query(ModelSetting).filter_by(key=key).count() == 0:
                    db.session.add(ModelSetting(key, value))
            db.session.commit()
            Logic.migration()
        except Exception as e: 
            logger.error('Exception:%s', e)
            logger.error(traceback.format_exc())

    @staticmethod
    def plugin_load():
        try:
            logger.debug('%s plugin_load', package_name)
            Logic.db_init()
            from plugin import plugin_info
            Util.save_from_dict_to_json(plugin_info, os.path.join(os.path.dirname(__file__), 'info.json'))

            tmp = os.path.join(path_data, package_name)
            if not os.path.exists(tmp):
                os.makedirs(tmp)
            if not os.path.exists(ModelSetting.get('path_accounts')):
                os.makedirs(ModelSetting.get('path_accounts'))
            try:
                from google_auth_oauthlib.flow import InstalledAppFlow
            except:
                os.system('pip install google_auth_oauthlib')
            tmp = os.path.join(os.path.dirname(__file__), 'bin')
            if os.path.exists(tmp):
                os.system('chmod 777 -R %s' % tmp)
        except Exception as e: 
            logger.error('Exception:%s', e)
            logger.error(traceback.format_exc())
    
    @staticmethod
    def plugin_unload():
        try:
            logger.debug('%s plugin_unload', package_name)
        except Exception as e: 
            logger.error('Exception:%s', e)
            logger.error(traceback.format_exc())


    @staticmethod
    def migration():
        pass

    ##################################################################################

    

    
