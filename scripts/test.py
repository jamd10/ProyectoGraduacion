"""Pruebas reproducibles sobre PostgreSQL y una cadena EVM desechables."""
from getpass import getpass
import json
import os
from pathlib import Path
import runpy
import socket
import subprocess
import sys
import tempfile
import time
from urllib.request import Request, urlopen
from uuid import uuid4

ROOT=Path(__file__).resolve().parents[1]
sys.dont_write_bytecode=True
sys.path.insert(0,str(ROOT/'backend'/'src'))


def main():
    import psycopg
    from psycopg import sql
    from sqlalchemy import create_engine
    from sqlalchemy.engine import URL
    from alembic import command
    from alembic.config import Config
    tools=runpy.run_path(str(ROOT/'scripts'/'local.py'))
    if tools['port_open'](8545):
        raise RuntimeError('Detén la aplicación y la cadena local antes de ejecutar las pruebas.')
    admin_password=os.environ.get('NEXOPASS_TEST_ADMIN_PASSWORD') or getpass('Contraseña de postgres para crear bases temporales: ')
    migrator_password=os.environ.get('NEXOPASS_TEST_MIGRATOR_PASSWORD') or getpass('Contraseña de nexopass_migrator: ')
    runtime_password=os.environ.get('NEXOPASS_TEST_RUNTIME_PASSWORD') or getpass('Contraseña de nexopass_app: ')
    node,_=tools['node_paths']()
    subprocess.run([str(node),str(ROOT/'contracts'/'compile.mjs')],cwd=ROOT,check=True)
    subprocess.run([str(node),'--test',str(ROOT/'contracts'/'tests'/'contract.test.mjs')],cwd=ROOT,check=True)
    name='nexopass_test_suite_'+uuid4().hex[:10]
    with socket.socket() as probe:probe.bind(('127.0.0.1',0));port=probe.getsockname()[1]
    env=os.environ.copy()
    env.update(PYTHONDONTWRITEBYTECODE='1',NEXOPASS_TEST_CHAIN_PORT=str(port),NEXOPASS_TEST_CHAIN_RPC_URL=f'http://127.0.0.1:{port}')
    with tempfile.TemporaryFile() as log, psycopg.connect(host='127.0.0.1',user='postgres',password=admin_password,dbname='postgres',autocommit=True) as admin:
        admin.execute(sql.SQL('CREATE DATABASE {} OWNER nexopass_migrator').format(sql.Identifier(name)))
        engine=create_engine(URL.create('postgresql+psycopg',username='nexopass_migrator',password=migrator_password,host='127.0.0.1',database=name),hide_parameters=True)
        chain=None
        try:
            with engine.begin() as connection:
                cfg=Config(str(ROOT/'backend'/'alembic.ini'));cfg.attributes['connection']=connection
                command.upgrade(cfg,'head');command.check(cfg)
            runpy.run_path(str(ROOT/'backend'/'scripts'/'prepare_runtime.py'))['provision_runtime'](admin_password,runtime_password,database=name)
            env.update(NEXOPASS_TEST_DATABASE_URL=engine.url.render_as_string(hide_password=False),NEXOPASS_TEST_ADMIN_PASSWORD=admin_password,NEXOPASS_TEST_RUNTIME_PASSWORD=runtime_password)
            chain=subprocess.Popen([str(node),str(ROOT/'contracts'/'test-server.mjs')],cwd=ROOT,env=env,stdout=log,stderr=log)
            deadline=time.monotonic()+20
            while True:
                try:
                    payload=json.dumps({'jsonrpc':'2.0','id':1,'method':'eth_chainId','params':[]}).encode()
                    with urlopen(Request(env['NEXOPASS_TEST_CHAIN_RPC_URL'],data=payload,headers={'Content-Type':'application/json'}),timeout=2) as response:
                        if json.load(response)['result']!='0x7a69':raise RuntimeError('Cadena de prueba incompatible')
                    break
                except OSError:
                    if chain.poll() is not None or time.monotonic()>deadline:raise RuntimeError('No inició la cadena de pruebas')
                    time.sleep(.1)
            result=subprocess.run([sys.executable,'-B','-m','pytest',str(ROOT/'backend'/'tests'),'-q','--tb=short'],cwd=ROOT,env=env)
            if result.returncode:return result.returncode
            with engine.begin() as connection:
                cfg=Config(str(ROOT/'backend'/'alembic.ini'));cfg.attributes['connection']=connection
                command.downgrade(cfg,'base')
                command.upgrade(cfg,'head')
                command.check(cfg)
            print('Suite completa y ciclo de migraciones verificados; las bases de prueba se eliminarán.')
        finally:
            if chain and chain.poll() is None:chain.terminate();chain.wait(timeout=10)
            engine.dispose()
            admin.execute(sql.SQL('DROP DATABASE {} WITH (FORCE)').format(sql.Identifier(name)))
    return 0


if __name__=='__main__':
    try:raise SystemExit(main())
    except KeyboardInterrupt:raise SystemExit(130)
    except Exception:
        print('Las pruebas no pudieron completarse. Revisa dependencias, servicios y credenciales; no se muestran datos sensibles.')
        raise SystemExit(1)
