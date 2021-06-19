from werkzeug.exceptions import Unauthorized
from broker.ga4gh.broker.endpoints.repositories import generate_id
from typing import (Dict)
from random import choice

from flask import (current_app)
import string
import logging

from pymongo.errors import DuplicateKeyError
from broker.errors.exceptions import (InternalServerError, NotFound, RepositoryNotFound)

logger = logging.getLogger(__name__)

def register_builds(repository_id: str, access_token: str,data: Dict):
    retries=3
    db_collection_builds = (
        current_app.config['FOCA'].db.dbs['brokerStore'].
        collections['builds'].client
    )
    db_collection_repositories = (
        current_app.config['FOCA'].db.dbs['brokerStore'].
        collections['repositories'].client
    )
    id_length = (
            current_app.config['FOCA'].endpoints['repository']['id_length']
    )
    id_charset: str = (
            current_app.config['FOCA'].endpoints['repository']['id_charset']
    )
    try:
        id_charset = eval(id_charset)
    except Exception:
        id_charset = ''.join(sorted(set(id_charset)))
    
    dataFromDB = db_collection_repositories.find_one({'id':repository_id})
    if dataFromDB != None:
        if dataFromDB['access_token'] == access_token:
            for i in range(retries + 1):
                logger.debug(f"Trying to insert/update object: try {i}" + str(data))
                data['id'] = repository_id + generate_id(
                    charset=id_charset, 
                    length=id_length, 
                )
                db_collection_repositories.update({"id": repository_id}, {"$push":{"buildList": data['id']}} )
                try:
                    data['finished_at'] = "2021-06-11T17:32:28Z"
                    data['started_at'] = "2021-06-11T17:32:28Z"
                    data['status'] = "UNKNOWN"
                    db_collection_builds.insert_one(data)
                    break
                except DuplicateKeyError:
                    continue
            return {'id': data['id']}
        else:
            raise Unauthorized
    else:
        raise NotFound



def get_builds(repository_id: str):
    db_collection_repositories = (
        current_app.config['FOCA'].db.dbs['brokerStore'].
        collections['repositories'].client
    )
    data=[]
    dataFromDB = db_collection_repositories.find_one({'id':repository_id})
    if dataFromDB != None:
        for build_id in dataFromDB['buildList']:
            build_data = get_build_info(repository_id, build_id)
            build_data['id'] = build_id
            data.append(build_data)
        logger.info('mData   : '  + str(data))
        #get_build_info()
        return data
    else:
        raise NotFound


def get_build_info(repository_id: str, build_id: str):
    db_collection_builds = (
        current_app.config['FOCA'].db.dbs['brokerStore'].
        collections['builds'].client
    )
    try:
        data= db_collection_builds.find( 
        {'id':build_id}, {'_id': False}
        ).limit(1).next()
        del data['id']
        return data
    except RepositoryNotFound:
        raise NotFound  