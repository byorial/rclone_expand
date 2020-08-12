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
                #ret = ',<br>'.join(email_list)
                #return jsonify({'data':ret})       
                return jsonify(email_list)
                    

        except Exception as e: 
            logger.error('Exception:%s', e)
            logger.error(traceback.format_exc())
    
    @staticmethod
    def api(sub, req):
        try:
            pass
        except Exception as e: 
            logger.error('Exception:%s', e)
            logger.error(traceback.format_exc())
 
    ###################


    @staticmethod
    def scheduler_function():
        LogicTorrentUpload.task()
        return
        if app.config['config']['use_celery']:
            result = LogicTorrentUpload.task.apply_async()
            result.get()
        else:
            LogicTorrentUpload.task()

    @staticmethod
    def reset_db():
        try:
            #db.session.query(ModelItem).delete()
            #db.session.commit()
            return True
        except Exception as e: 
            logger.error('Exception:%s', e)
            logger.error(traceback.format_exc())
            return False

    @staticmethod
    @celery.task
    def task():
        try:
            logger.debug('111111111111111111111111')
            # 목록
            src_list = RcloneTool.lsjson(rclone_path, rclone_config_path, remote_upload, option=['--dirs-only'])

            #[{u'MimeType': u'inode/directory', u'IsDir': True, u'Name': u'90994', u'ModTime': u'2020-08-04T12:59:56.767Z', u'Path': u'90994', u'ID': u'13SwQyF49hq3Irp5xmY8RPCBMV1PtLWBP', u'Size': -1},

            # 이동
            # 타켓 폴더 기준으로 내용을 채우므로 content
            # folder_name, server_filename = ''

            # 비어있는 폴더가 있을수 잇다.
            # 업로더가 rclone 으로 올리는 중에 빈 폴더만 있을 수 있다.

            for item in src_list:
                item_remote = remote_upload + '/' + item['Name']
                logger.debug(item_remote)
                item_file_list = RcloneTool.lsjson(rclone_path, rclone_config_path, item_remote, option=['--files-only', '-R'])
                file_count = 0
                torrent_size = 0
                for tmp in item_file_list:
                    file_count += 1
                    torrent_size += tmp['Size']
                
                logger.debug(item)
                logger.debug(item_file_list)
                logger.debug(file_count)
                logger.debug(torrent_size)
                name_server_id, name_file_count, name_torrent_size, name_magnet_hash, name_uploader = item['Name'].split('_')
                name_file_count = int(name_file_count)
                name_torrent_size = int(name_torrent_size)
                
                logger.debug('name_file_count:%s', name_file_count)
                logger.debug('name_torrent_size:%s', name_torrent_size)
                if file_count >= name_file_count and torrent_size >= name_torrent_size:
                    # 복사
                    ret = RcloneTool.do_action(rclone_path, rclone_config_path, 'move', 'category', remote_share_target_folderid, '', '', item_remote, 'real', option=['--delete-empty-src-dirs'])        
                    logger.debug(ret)

                    rmdir_ret = RcloneTool.rmdir(rclone_path, rclone_config_path, item_remote)
                    logger.debug(rmdir_ret)
                    LogicTorrentUpload.process_one(name_server_id, name_magnet_hash, name_uploader, ret['folder_id'])
            """
            return
            ret = RcloneTool.do_action(rclone_path, rclone_config_path, 'move', 'content', remote_share_target_folderid, '', '', remote_upload, 'real', option=['--delete-empty-src-dirs'])
            logger.debug(ret)
            logger.debug(src_list)

            target_list = RcloneTool.lsjson(rclone_path, rclone_config_path, remote_share_target, option=['--dirs-only'])

            target_list = sorted(target_list, key=lambda k:k['Path'])


            logger.debug('33333333333')
            logger.debug(target_list)
            for item in target_list:
                logger.debug('2222222222222222')
                logger.debug(item['Name'])
                for src in src_list:
                    if item['Name'] == src['Name']:
                        tmp = item['Name'].split('_')
                        server_id = tmp[0]
                        magnet = uploader = None
                        if len(tmp) > 1:
                            magnet = tmp[1]
                        if len(tmp) > 2:
                            uploader = tmp[2]
                        
                        folderid = AESCipher.encrypt(str(item['ID']), Vars.key)
                        LogicTorrentUpload.process_one(server_id, magnet, uploader, folderid)       
            """
        except Exception as e: 
            logger.error('Exception:%s', e)
            logger.error(traceback.format_exc())
            return False
    #################################################################

    @staticmethod
    def process_one(server_id, magnet, uploader, folderid):
        try:
            logger.debug('server_id : %s', server_id)
            logger.debug('magnet : %s', magnet)
            logger.debug('uploader : %s', uploader)
            logger.debug('folderid : %s', folderid)

            telegram = {}
            telegram['plugin'] = 'downloader'
            telegram['data'] = {'server_id':server_id, 'magnet_hash':magnet, 'uploader':uploader, 'folderid':folderid}
            text = json.dumps(telegram, indent=2)

            import requests
            response = requests.post("https://sjva.me/sjva/torrent_upload.php", data={'data':text})
            logger.debug(response.content)

            
            from framework.common.telegram_bot import TelegramBot
            TelegramBot.super_send_message(text)
            time.sleep(0.5)

            
        except Exception as e: 
            logger.error('Exception:%s', e)
            logger.error(traceback.format_exc())





















    @staticmethod
    def process_folder(folder_name, force=False):
        try:
            #source = ModelSetting.get('av_sub_library_path')
            source = av_sub_library_path
            # 폴더 있는지 확인
            folder_path = os.path.join(source, folder_name)
            if not os.path.exists(folder_path) :
                pass
            item = ModelAVSubItem.get_by_folder_name(folder_name)
            if item is None:
                item = ModelAVSubItem.create(folder_name)

            if item.meta_json is None and (item.meta_try_count is None or item.meta_try_count == 0):# or item.meta_title is None or item.meta_type == 'javdb':
                meta = LogicAVSub.get_meta(folder_name)
                if meta is not None and 'update' in meta:
                    item.meta_json = meta
                    item.meta_type = meta['type']
                    item.meta_code = meta['update']['code']
                    item.meta_title = meta['update']['title_ko']
                    item.meta_poster = meta['update']['poster']
                    item.meta_summury = meta['update']['summary_ko']
                    try: item.meta_actor = meta['update']['performer'][0]['name_kor']
                    except: pass
                    item.meta_date = meta['update']['date']
                    item.save()
                else:
                    if item.meta_try_count is None:
                        item.meta_try_count = 1
                    else:
                        item.meta_try_count += 1
            
            if item.folder_id is None:
                item.folder_id = LogicAVSub.get_folderid(folder_name)
                logger.debug(item.folder_id)
                from framework.common.util import AESCipher
                item.folder_id_encrypted = AESCipher.encrypt(str(item.folder_id), Vars.key)
                logger.debug(item.folder_id_encrypted)
                item.save()

            # 파일 목록
            folder_path = os.path.join(source, folder_name)
            video_count = 0
            for f in os.listdir(folder_path):
                tmp = os.path.splitext(f)
                if tmp[1].lower() in ['.mp4', '.mkv', '.avi', '.wmv']:
                    video_count += 1

            if item.video_count != video_count or force:
                item.video_count = video_count
                
                for f in os.listdir(folder_path):
                    filepath = os.path.join(folder_path, f)
                    splitext = os.path.splitext(f)
                    if splitext[1].lower() in ['.mp4', '.mkv', '.avi', '.wmv']:
                        file_item = ModelAVSubFile.get_by_filename(f)
                        if file_item is not None:
                            db.session.delete(file_item)
                            db.session.commit()
                            file_item = None

                        if file_item is None:
                            file_item = ModelAVSubFile.create(f, item.id)
                            from system.logic_command import SystemLogicCommand
                            command = ['ffprobe', '-v', 'quiet', '-print_format', 'json', '-show_format', '-show_streams', filepath]
                            ff_data = SystemLogicCommand.execute_command_return(command, format='json')
                            if ff_data is not None:
                                file_item.ffprobe_json = ff_data
                                file_item.filesize = int(ff_data['format']['size'])
                                file_item.duration = int(float(ff_data['format']['duration']))
                                file_item.bitrate = int(ff_data['format']['bit_rate'])
                                video_stream = None
                                for idx, tmp in enumerate(ff_data['streams']):
                                    if tmp['codec_type'] == 'video':
                                        video_stream = tmp
                                        break
                                if video_stream is not None:
                                    file_item.codec_name = video_stream['codec_name']
                                    file_item.width = int(video_stream['width'])
                                    file_item.height = int(video_stream['height'])
                                file_item.save()

                            # srt
                            srt_filepath = filepath.replace(splitext[1], '.ko.srt')
                            if not os.path.exists(srt_filepath):
                                originame_srt_filepath = os.path.join(folder_path, folder_name + '.ko.srt')
                                if os.path.exists(originame_srt_filepath):
                                    import shutil
                                    shutil.copyfile(originame_srt_filepath, srt_filepath)
                            #text = json.dumps(ret, indent=2)
                            #logger.debug(text)
                #item.folder_size = os.stat(folder_path).st_size
                item.save()          
            logger.debug('END:%s\n%s %s\n%s\n%s', folder_name, item.meta_type, item.meta_title, item.folder_id, item.video_count)

      

        except Exception as e: 
            logger.error('Exception:%s', e)
            logger.error(traceback.format_exc())
            return False
    


    @staticmethod
    def get_meta(code):
        try:
            import framework.common.fileprocess as FileProcess
            meta = {}

            tmp = FileProcess.dmm_search(code)
            if len(tmp) != 0:
                if tmp[0]['score'] == 100:
                    meta['type'] = 'dmm'
                    meta['search'] = tmp
                    meta['update'] = FileProcess.dmm_update(tmp[0]['id'])
                    return meta

            tmp = FileProcess.javdb_search(code)
            if len(tmp) != 0:
                if tmp[0]['score'] == 100:
                    meta['type'] = 'javdb'
                    meta['search'] = tmp
                    meta['update'] = FileProcess.javdb_update(tmp[0]['id'])
                    meta['update']['poster'] = meta['update']['poster'].split('url=')[1].split('&apikey')[0]
                    return meta
        except Exception as e: 
            logger.error('Exception:%s', e)
            logger.error(traceback.format_exc())

    @staticmethod
    def get_folderid(folder_name):
        try:
            from .plugin import rclone_path, rclone_config_path
            remote_path = remote_path_root + '/' + folder_name
            data = RcloneTool.lsjson(rclone_path, rclone_config_path, remote_path_root, option=['--dirs-only'])
                
            for item in data:
                if item['IsDir']:
                    if item['Name'] == folder_name:
                        return item['ID']
        except Exception as e: 
            logger.error('Exception:%s', e)
            logger.error(traceback.format_exc())
