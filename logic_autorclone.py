# -*- coding: utf-8 -*-
#########################################################
# python
import os
from datetime import datetime
import traceback
import logging
import subprocess
import time
import re
import threading
import json
import platform
import shutil

# third-party
from flask import Blueprint, request, Response, send_file, render_template, redirect, jsonify

# sjva 공용
from framework import app, db, scheduler, path_app_root, celery, path_data
from framework.job import Job
from framework.util import Util
from framework.common.share import RcloneTool, Vars
from system.model import ModelSetting as SystemModelSetting
from framework.common.util import AESCipher

# 패키지
from .plugin import logger, package_name
from .model import ModelSetting

#########################################################


class LogicAutoRclone(object):
    @staticmethod
    def process_ajax(sub, req):
        try:
            if sub == 'sa_create_new_only':
                python_file = os.path.join(os.path.dirname(__file__), 'gen_sa_accounts.py')
                from system.logic_command import SystemLogicCommand
                return_log = SystemLogicCommand.start('AutoRclone', [
                    ['msg', '잠시만 기다리세요'],
                    ['python', python_file, '--quick-setup', '1', '--new-only', '--path', ModelSetting.get('path_accounts'), '--credentials', ModelSetting.get('path_credentials'), '--token', ModelSetting.get('path_token')],
                    ['msg', '완료'],
                ])
                return jsonify('')
            elif sub == 'auth_step1':
                from .gen_sa_accounts import auth_step1
                url, _ = auth_step1(credentials=ModelSetting.get('path_credentials'), token=ModelSetting.get('path_token'))
                return jsonify(url)
            elif sub == 'auth_step2':
                from .gen_sa_accounts import auth_step2
                code = req.form['code']
                auth_step2(code, token=ModelSetting.get('path_token'))
                return jsonify(os.path.exists(ModelSetting.get('path_token')))
            elif sub == 'split_json':
                import glob
                accounts_dir = ModelSetting.get('path_accounts')
                sa_files = glob.glob(os.path.join(accounts_dir, '*.json'))
                count = 0
                for i, filename in enumerate(sa_files):
                    json_path = os.path.join(accounts_dir, filename)
                    data = json.loads(open(json_path,'r').read())
                    target_dir = os.path.join(accounts_dir, data['project_id'])
                    if not os.path.exists(target_dir):
                        os.makedirs(target_dir)
                    shutil.move(json_path, target_dir)
                    count += 1
                return jsonify(count)
            elif sub == 'gen_email':
                import glob
                accounts_dir = ModelSetting.get('path_accounts')
                sa_files = glob.glob(os.path.join(accounts_dir, '*.json'))
                email_list = []
                for filename in sa_files:
                    json_path = os.path.join(accounts_dir, filename)
                    data = json.loads(open(json_path,'r').read())
                    email_list.append(data['client_email'])
                return jsonify(email_list)
        except Exception as e: 
            logger.error('Exception:%s', e)
            logger.error(traceback.format_exc())