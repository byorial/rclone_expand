# -*- coding: utf-8 -*-
#########################################################
# python
import traceback
from datetime import datetime,timedelta
import json
import os
import re

# third-party
from sqlalchemy import or_, and_, func, not_, desc
from sqlalchemy.orm import backref


# sjva 공용
from framework import app, db, path_app_root
from framework.util import Util

# 패키지
from .plugin import logger, package_name

app.config['SQLALCHEMY_BINDS'][package_name] = 'sqlite:///%s' % (os.path.join(path_app_root, 'data', 'db', '%s.db' % package_name))
#########################################################
        
class ModelSetting(db.Model):
    __tablename__ = '%s_setting' % package_name
    __table_args__ = {'mysql_collate': 'utf8_general_ci'}
    __bind_key__ = package_name

    id = db.Column(db.Integer, primary_key=True)
    key = db.Column(db.String(100), unique=True, nullable=False)
    value = db.Column(db.String, nullable=False)
 
    def __init__(self, key, value):
        self.key = key
        self.value = value

    def __repr__(self):
        return repr(self.as_dict())

    def as_dict(self):
        return {x.name: getattr(self, x.name) for x in self.__table__.columns}

    @staticmethod
    def get(key):
        try:
            return db.session.query(ModelSetting).filter_by(key=key).first().value.strip()
        except Exception as e:
            logger.error('Exception:%s %s', e, key)
            logger.error(traceback.format_exc())
            return None
            
    
    @staticmethod
    def get_int(key):
        try:
            return int(ModelSetting.get(key))
        except Exception as e:
            logger.error('Exception:%s %s', e, key)
            logger.error(traceback.format_exc())
    
    @staticmethod
    def get_bool(key):
        try:
            return (ModelSetting.get(key) == 'True')
        except Exception as e:
            logger.error('Exception:%s %s', e, key)
            logger.error(traceback.format_exc())

    @staticmethod
    def set(key, value):
        try:
            item = db.session.query(ModelSetting).filter_by(key=key).with_for_update().first()
            if item is not None:
                item.value = value.strip()
                db.session.commit()
            else:
                db.session.add(ModelSetting(key, value.strip()))
        except Exception as e:
            logger.error('Exception:%s %s', e, key)
            logger.error(traceback.format_exc())

    @staticmethod
    def to_dict():
        try:
            ret = Util.db_list_to_dict(db.session.query(ModelSetting).all())
            ret['package_name'] = package_name
            return ret 
        except Exception as e:
            logger.error('Exception:%s %s', e, key)
            logger.error(traceback.format_exc())


    @staticmethod
    def setting_save(req):
        try:
            for key, value in req.form.items():
                if key in ['scheduler', 'is_running']:
                    continue
                if key.startswith('global_') or key.startswith('tmp_'):
                    continue
                logger.debug('Key:%s Value:%s', key, value)
                entity = db.session.query(ModelSetting).filter_by(key=key).with_for_update().first()
                entity.value = value
            db.session.commit()
            return True                  
        except Exception as e: 
            logger.error('Exception:%s', e)
            logger.error(traceback.format_exc())
            logger.debug('Error Key:%s Value:%s', key, value)
            return False

    @staticmethod
    def get_list(key, delimeter):
        try:
            value = ModelSetting.get(key)
            values = [x.strip() for x in value.split(delimeter)]
            values = Util.get_list_except_empty(values)
            return values
        except Exception as e: 
            logger.error('Exception:%s', e)
            logger.error(traceback.format_exc())
            logger.error('Error Key:%s Value:%s', key, value)


class WSModelItem(db.Model):
    __tablename__ = '%s_wsitem' % package_name
    __table_args__ = {'mysql_collate': 'utf8_general_ci'}
    __bind_key__ = package_name

    id = db.Column(db.Integer, primary_key=True)
    json = db.Column(db.JSON)
    created_time = db.Column(db.DateTime)

    doc_id = db.Column(db.String)
    doc_title = db.Column(db.String)
    ws_id = db.Column(db.Integer)
    ws_title = db.Column(db.String)
    doc_url = db.Column(db.String)
    in_schedule = db.Column(db.Boolean)
    updated_time = db.Column(db.DateTime)
    copy_count = db.Column(db.Integer)
    total_count = db.Column(db.Integer)
    is_running = db.Column(db.Boolean)

    def __init__(self, info):
        self.created_time = datetime.now()
        self.doc_id = info['doc_id']
        self.doc_title = info['doc_title']
        self.doc_url = info['doc_url']
        self.ws_id = info['ws_id']
        self.ws_title = info['ws_title']
        self.in_schedule = False
        self.updated_time = None
        self.copy_count = 0
        self.total_count = 0
        self.is_running = False

    def __repr__(self):
        return repr(self.as_dict())

    def as_dict(self):
        ret = {x.name: getattr(self, x.name) for x in self.__table__.columns}
        ret['created_time'] = self.created_time.strftime('%Y-%m-%d %H:%M:%S') 
        ret['updated_time'] = self.updated_time.strftime('%Y-%m-%d %H:%M:%S') if self.updated_time is not None else None
        return ret

    def save(self):
        try:
            db.session.add(self)
            db.session.commit()
        except Exception as e:
            logger.error('Exception:%s', e)
            logger.error(traceback.format_exc())

    def save_as_dict(d):
        try:
            entity = WSModelItem()
            entity.doc_id = unicode(d['doc_id'])
            entity.doc_title = unicode(d['doc_title'])
            entity.ws_id = unicode(d['ws_id'])
            entity.ws_title = unicode(d['ws_title'])
            entity.doc_url = unicode(d['doc_url'])
            entity.in_schedule = d['in_schedule']

            db.session.add(entity)
            db.session.commit()
        except Exception as e:
            logger.error(d)
            logger.error('Exception:%s', e)

    @staticmethod
    def create(info):
        try:
            entity = WSModelItem.get_entity_by_wsinfo(info['doc_id'], int(info['ws_id']))
            if entity is None:
                entity = WSModelItem(info)
                entity.save()
                return entity
            return None
        except Exception, e:
            logger.error('Exception:%s', e)
            logger.error(traceback.format_exc())

    @staticmethod
    def get_entity_by_wsinfo(doc_id, ws_id):
        try:
            logger.debug('doc_id:%s, ws_id:%d', doc_id, ws_id)
            conditions = []
            conditions.append(WSModelItem.doc_id==doc_id)
            conditions.append(WSModelItem.ws_id==ws_id)

            query = db.session.query(WSModelItem).filter(and_(*conditions))
            count = query.count()
            if count > 0:
                entity = query.with_for_update().first()
                return entity
            return None
        except Exception, e:
            logger.error('Exception:%s', e)
            logger.error(traceback.format_exc())
            return None
            
    @staticmethod
    def get_scheduled_list():
        try:
            logger.debug('start: get_scheduled_list')
            query = db.session.query(WSModelItem).filter_by(in_schedule = True)
            logger.debug('count: %d', query.count())
            return query.all()
        except Exception, e:
            logger.error('Exception:%s', e)
            logger.error(traceback.format_exc())
            return None


    @staticmethod
    def ws_list(req):
        try:
            ret = {}
            page = 1
            page_size = 30
            job_id = ''
            search = ''
            if 'page' in req.form:
                page = int(req.form['page'])
            if 'search_word' in req.form:
                search = req.form['search_word']
            order = req.form['order'] if 'order' in req.form else 'desc'

            query = WSModelItem.make_query(search=search, order=order)
            count = query.count()
            query = query.limit(page_size).offset((page-1)*page_size)
            lists = query.all()
            ret['list'] = [item.as_dict() for item in lists]
            ret['paging'] = Util.get_paging_info(count, page, page_size)
            return ret
        except Exception, e:
            logger.error('Exception:%s', e)
            logger.error(traceback.format_exc())

    @staticmethod
    def make_query(search='', order='desc'):
        query = db.session.query(WSModelItem)
        if search is not None and search != '':
            conditions = []
            if search.find('|') != -1:
                for tt in search.split('|'):
                    if tt != '':
                        conditions.append(WSModelItem.doc_title.like('%'+tt.strip()+'%'))
                        conditions.append(WSModelItem.ws_title.like('%'+tt.strip()+'%'))
            elif search.find(',') != -1:
                for tt in search.split(','):
                    if tt != '':
                        conditions.append(WSModelItem.doc_title.like('%'+tt.strip()+'%'))
                        conditions.append(WSModelItem.ws_title.like('%'+tt.strip()+'%'))
            else:
                conditions.append(WSModelItem.doc_title.like('%'+search+'%'))
                conditions.append(WSModelItem.ws_title.like('%'+search+'%'))

            query = query.filter(or_(*conditions))
        if order == 'desc':
            query = query.order_by(desc(WSModelItem.id))
        else:
            query = query.order_by(WSModelItem.id)

        return query

    @staticmethod
    def get(id):
        try:
            entity = db.session.query(WSModelItem).filter_by(id=id).with_for_update().first()
            return entity
        except Exception, e:
            logger.error('Exception:%s', e)
            logger.error(traceback.format_exc())

    @staticmethod
    def delete(id):
        try:
            logger.debug( "delete")
            db.session.query(WSModelItem).filter_by(id=id).delete()
            db.session.commit()

        except Exception, e:
            logger.error('Exception:%s', e)
            logger.error(traceback.format_exc())

    @staticmethod
    def ws_ir_init():
        try:
            for e in db.session.query(WSModelItem).filter(WSModelItem.is_running == True).all():
                e.is_running = False
            db.session.commit()

        except Exception, e:
            logger.error('Exception:%s', e)
            logger.error(traceback.format_exc())

class ListModelItem(db.Model):
    __tablename__ = '%s_listitem' % package_name
    __table_args__ = {'mysql_collate': 'utf8_general_ci'}
    __bind_key__ = package_name

    id = db.Column(db.Integer, primary_key=True)
    json = db.Column(db.JSON)
    created_time = db.Column(db.DateTime)

    sheet_id = db.Column(db.String)  #WSModelItem.ID
    title = db.Column(db.String)
    title2 = db.Column(db.String)
    folder_id = db.Column(db.String)
    category = db.Column(db.String)
    copy_count = db.Column(db.Integer)
    obj_num = db.Column(db.Integer)
    str_size = db.Column(db.String)
    copied_time = db.Column(db.DateTime)
    byte_size = db.Column(db.Integer)

    updated_time = db.Column(db.DateTime)

    def __init__(self, info):
        self.created_time = datetime.now()
        self.sheet_id = info['sheet_id']
        self.title = info['title']
        self.title2 = info['title2']
        self.folder_id = info['folder_id']
        self.category = info['category']
        self.copied_time = None
        self.copy_count = 0
        self.obj_num = info['obj_num']
        self.str_size = info['str_size']
        self.byte_size = info['byte_size']
        self.updated_time = datetime.now()

    def __repr__(self):
        return repr(self.as_dict())

    def as_dict(self):
        ret = {x.name: getattr(self, x.name) for x in self.__table__.columns}
        ret['created_time'] = self.created_time.strftime('%Y-%m-%d %H:%M:%S') 
        ret['copied_time'] = self.copied_time.strftime('%Y-%m-%d %H:%M:%S') if self.copied_time is not None else None
        ret['updated_time'] = self.updated_time.strftime('%Y-%m-%d %H:%M:%S') if self.updated_time is not None else None

        return ret

    def save(self):
        try:
            db.session.add(self)
            db.session.commit()
        except Exception as e:
            logger.error('Exception:%s', e)
            logger.error(traceback.format_exc())

    def save_as_dict(d):
        try:
            entity = ListModelItem()
            entry.sheet_id = unicode(d['sheet_id'])
            entry.title = unicode(d['title'])
            entry.title2 = unicode(d['title2'])
            entry.folder_id = unicode(d['folder_id'])
            entry.category = unicode(d['category'])
            entry.copy_count = d['copy_count']
            entry.obj_num = d['obj_num']
            entry.category = unicode(d['category'])
            entry.str_size = unicode(d['str_size'])
            entry.byte_size = d['str_size']

            db.session.add(entity)
            db.session.commit()
        except Exception as e:
            logger.error(d)
            logger.error('Exception:%s', e)


    @staticmethod
    def create(info):
        try:
            entity = ListModelItem.get_entity_by_folder_id(info['folder_id'])
            if entity is None:
                entity = ListModelItem(info)
                entity.save()
                return entity
            return None
        except Exception, e:
            logger.error('Exception:%s', e)
            logger.error(traceback.format_exc())

 
    @staticmethod
    def update_with_info(id, info):
        try:
            updated = False
            e = ListModelItem.get(id)
            if e is None:
                return None
            if e.title != info['title']:
                e.title = info['title']
                updated = True
            if e.title2 != info['title2']:
                e.title2 = info['title2']
                updated = True
            if e.category != info['category']:
                e.category = info['category']
                updated = True
            if e.obj_num != info['obj_num']:
                e.obj_num = info['obj_num']
                updated = True
            if e.str_size != info['str_size']:
                e.str_size = info['str_size']
                updated = True
            if e.byte_size != info['byte_size']:
                e.byte_size = info['byte_size']
                updated = True

            if updated:
                e.updated_time = datetime.now()
                e.save()
                return True
            return False

        except Exception, e:
            logger.error('Exception:%s', e)
            logger.error(traceback.format_exc())
            return False

    @staticmethod
    def get_entity_by_folder_id(folder_id):
        try:
            #logger.debug('folder_id:%s', folder_id)
            entity = db.session.query(ListModelItem).filter_by(folder_id=folder_id).with_for_update().first()
            return entity
        except Exception, e:
            logger.error('Exception:%s', e)
            logger.error(traceback.format_exc())
            return None

    @staticmethod
    def get_schedule_target_items(sheet_id):
        try:
            query = db.session.query(ListModelItem).filter_by(sheet_id=sheet_id)

            copy_count_limit = ModelSetting.get_int('copy_count_limit')
            if copy_count_limit != 0:
                query = query.filter(ListModelItem.copy_count < copy_count_limit)

            if ModelSetting.get_bool('copy_delay_use'):
                copy_delay = ModelSetting.get_int('copy_delay')
                if copy_delay != 0:
                    target_time = datetime.now() - timedelta(minutes=copy_delay)
                    query = query.filter(ListModelItem.updated_time < target_time)

            categories = ModelSetting.get_list('category_rules', '\n')
            if len(categories) > 0:
                query = query.filter(ListModelItem.category.in_(categories))
            xcategories = ModelSetting.get_list('except_category_rules', '\n')
            if len(xcategories) > 0:
                query = query.filter(not_(ListModelItem.category.in_(xcategories)))
            logger.info('get_schedule_target_items: count(%d)', query.count())
            return query.all()
        except Exception, e:
            logger.error('Exception:%s', e)
            logger.error(traceback.format_exc())
            return None

    @staticmethod
    def item_list(req):
        try:
            logger.debug(req.form)
            ret = {}
            page = 1
            page_size = 30
            search = ''
            
            if 'sheet_id' in req.form: sheet_id = req.form['sheet_id']
            if 'page' in req.form: page = int(req.form['page'])
            if 'search_word' in req.form: search = req.form['search_word'] 
            if 'option' in req.form: option = req.form['option']
            if 'copied' in req.form: copied = req.form['copied']
            order = req.form['order'] if 'order' in req.form else 'desc'

            query = ListModelItem.make_query(sheet_id=sheet_id, search=search, option=option, copied=copied, order=order)
            if query is None: return ret

            count = query.count()
            logger.debug(count)
            query = query.limit(page_size).offset((page-1)*page_size)
            lists = query.all()
            #logger.debug(lists)
            ret['list'] = [item.as_dict() for item in lists]
            ret['paging'] = Util.get_paging_info(count, page, page_size)
            return ret
        except Exception, e:
            logger.error('Exception:%s', e)
            logger.error(traceback.format_exc())

    @staticmethod
    def make_query(sheet_id='', search='', option='', copied="all", order='desc'):
        query = db.session.query(ListModelItem)
        if sheet_id != '' and sheet_id != 'all':
            try:
                sheet_id = int(sheet_id)
                query = query.filter(ListModelItem.sheet_id==sheet_id)
            except ValueError, e:
                logger.error('Invalid sheet_id({sheet_id})'.format(sheet_id=sheet_id))
                return None

        if copied == 'true': query = query.filter(ListModelItem.copy_count > 0)
        elif copied == 'false': query = query.filter(ListModelItem.copy_count == 0)
	
        if search != '':
            if option == 'folder_id':
                query = query.filter(ListModelItem.folder_id.like('%'+search+'%'))
                return query
            elif option == 'category':
                query = query.filter(ListModelItem.category.like('%'+search+'%'))
            else: # title
                conditions = []
                conditions.append(ListModelItem.title.like('%'+search+'%'))
                conditions.append(ListModelItem.title2.like('%'+search+'%'))
                query = query.filter(or_(*conditions))

        if order == 'desc':
            query = query.order_by(desc(ListModelItem.id))
        elif order == 'up_desc':
            query = query.order_by(desc(ListModelItem.updated_time))
        elif order == 'up_asc':
            query = query.order_by(ListModelItem.updated_time)
        elif order == 'size_desc':
            query = query.order_by(desc(ListModelItem.byte_size))
        elif order == 'size_asc':
            query = query.order_by(ListModelItem.byte_size)
        else:
            query = query.order_by(ListModelItem.id)

        return query

    @staticmethod
    def get(id):
        try:
            entity = db.session.query(ListModelItem).filter_by(id=id).with_for_update().first()
            return entity
        except Exception, e:
            logger.error('Exception:%s', e)
            logger.error(traceback.format_exc())
            return None

    @staticmethod
    def delete(id):
        try:
            logger.debug( "delete")
            db.session.query(ListModelItem).filter_by(id=id).delete()
            db.session.commit()

        except Exception, e:
            logger.error('Exception:%s', e)
            logger.error(traceback.format_exc())


    @staticmethod
    def get_total_count(sheet_id):
        try:
            return db.session.query(ListModelItem).filter_by(sheet_id=sheet_id).count()
        except Exception, e:
            logger.error('Exception:%s', e)
            logger.error(traceback.format_exc())
            return 0


    @staticmethod
    def get_copy_count(sheet_id):
        try:
            return db.session.query(ListModelItem).filter(and_(ListModelItem.sheet_id == sheet_id, ListModelItem.copy_count > 0)).count()
        except Exception, e:
            logger.error('Exception:%s', e)
            logger.error(traceback.format_exc())
            return 0


