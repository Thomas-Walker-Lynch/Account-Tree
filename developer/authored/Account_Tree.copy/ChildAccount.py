# -*- mode: python; coding: utf-8; python-indent-offset: 2; indent-tabs-mode: nil -*-
"""
ChildAccount - making and deallocating a child account, on a
storage attached here, with the storage and the system kept in step.

  child__make        make a child account of a parent account: its storage
                     account and home, its system account, which the system
                     map records as the same account, its groups, and the
                     mount of its home
  child__deallocate  remove an account: its processes are ended, its system
                     account, its mount point, its sound FIFOs and the files
                     it left on this system are deleted, its sound records
                     deleted, its uids retired, and its home moved
                     into account-deallocated/ on its storage, which only the
                     administrator removes

Each is run under root, by Account-Tree_admin or by the request interpreter,
which checks the request against the records first. Each takes the lock plug
and unplug take, so none runs while a storage is plugged in or unplugged. A
work function reports through log; it returns None or False when it stops,
having logged why.

Deallocating an account keeps its row in the storage database, as every
database uid given out is kept, and renames it to the name of its home in
account-deallocated/, <name>.<time>, so the name can be given to a new
account.
"""

import os ,time
from pathlib import Path

import Database
import Storage
import SameAccount
import StoragePlug
import Request·Record as record
from Common import SEPARATOR ,DIRN__DEALLOCATED ,act ,valid_name ,dirpa__Account_Tree
from System import open_system_database


# --------------------------------------------------------------------------------
# finding an account

def storage__of(system_db ,row ,log):
  """
  (dirpa__root ,storage_db) of the storage carrying a system map row's
  storage account, the database opened for writing; None with an error
  logged when it is not attached here.
  """
  try:
    system_db__read = record.open__system()
    try:
      storage_db__read ,dirpa__root = record.storage_database__of(system_db__read ,row["database_uuid"])
      storage_db__read.close()
    finally:
      system_db__read.close()
  except record.RecordError as error:
    log.error(row["system_account__name"] ,str(error)); return None
  storage_db = Storage.open_storage_database(dirpa__root ,log)
  if storage_db is None: return None
  return dirpa__root ,storage_db

def account__in_use(name ,log):
  """
  (system_db ,row ,dirpa__root ,storage_db ,account) for a system account
  Account-Tree keeps in use here; None with an error logged.
  """
  system_db = open_system_database(log)
  if system_db is None: return None
  row = system_db.row("SELECT * FROM system_map WHERE system_account__name = ? AND state = 'in use'" ,(name,))
  if row is None:
    log.error(name ,"not an account Account-Tree keeps in use here"); return None
  found = storage__of(system_db ,row ,log)
  if found is None: return None
  dirpa__root ,storage_db = found
  account = storage_db.row("SELECT * FROM account WHERE database_uid = ?" ,(row["database_uid"],))
  if account is None:
    log.error(name ,f"its storage database has no account of database uid {row['database_uid']}"); return None
  return system_db ,row ,dirpa__root ,storage_db ,account

def list__child(storage_db ,account ,list__state):
  "the accounts of storage_db whose parent is account, in one of the states"
  return [a for a in storage_db.rows("SELECT * FROM account WHERE parent__database_uid = ? ORDER BY name" ,(account["database_uid"],))
          if a["state"] in list__state]


# --------------------------------------------------------------------------------
# make

def child__make(parent ,short_name ,log ,preview):
  """
  Make the child account <parent>·<short_name> of the system account parent,
  on parent's storage. Returns {"name" ,"database_uid" ,"system_uid"}, or
  None when it stopped. The limits are counted again here, under the lock,
  as the guard's count was made before it.
  """
  if SEPARATOR in short_name:
    log.error(short_name ,f"a short name holds no '{SEPARATOR}'"); return None
  name = parent + SEPARATOR + short_name
  problem = valid_name(name)
  if problem:
    log.error(name ,problem); return None
  with StoragePlug.Lock():
    found = account__in_use(parent ,log)
    if found is None: return None
    system_db ,row__parent ,dirpa__root ,storage_db ,account__parent = found
    if account__parent["name"] != parent:
      log.error(parent ,f"its storage account is named {account__parent['name']}, a branch;"
                " a child account is made only for an account whose two names are the same"); return None
    if account__parent["state"] != "active":
      log.error(parent ,f"is {account__parent['state']}"); return None
    list__problem = record.limit__problem(system_db ,storage_db ,account__parent)
    if list__problem:
      for problem in list__problem: log.error(name ,problem)
      return None

    count_of__error = log.count_of__error
    Storage.account__make(dirpa__root ,name ,None ,parent ,True ,log ,preview)
    if log.count_of__error > count_of__error: return None
    if preview:
      log.line("mounted" ,f"/home/{name}" ,"idmapped, once made")
      return {"name": name ,"database_uid": 0 ,"system_uid": 0}

    row = system_db.row("SELECT * FROM system_map WHERE system_account__name = ? AND state = 'in use'" ,(name,))
    if row is None:
      log.error(name ,"the system map does not record it, though it was made"); return None
    storage_db = Storage.open_storage_database(dirpa__root ,log)
    Storage.attach_account(dirpa__Account_Tree(dirpa__root) ,storage_db ,row ,log ,preview)
    if log.count_of__error > count_of__error: return None
    return {"name": name ,"database_uid": row["database_uid"] ,"system_uid": row["system_uid"]}


# --------------------------------------------------------------------------------
# deallocate

def child__deallocate(name ,log ,preview):
  """
  Remove an account: end its processes, unmount its home and
  delete its mount point, delete its system account and the files it left on
  this system, retire its row of the system map and its database uid, and
  move its home into account-deallocated/ on its storage. Refused while an
  account below it is not deallocated. Returns True when it was done, or
  would be.
  """
  with StoragePlug.Lock():
    found = account__in_use(name ,log)
    if found is None: return False
    system_db ,row ,dirpa__root ,storage_db ,account = found
    if account["parent__database_uid"] is None:
      log.error(name ,"a login account, a child of root, or one whose parent is on another storage, is not deallocated here"); return False
    # deprecated: a state this version no longer makes, which an account can still be in
    if account["state"] not in ("active" ,"deprecated"):
      log.error(name ,f"is {account['state']}"); return False
    below = list__child(storage_db ,account ,("active" ,"deprecated"))
    if below:
      log.error(name ,"accounts below it remain; deallocate them first: " + ", ".join(a["name"] for a in below)); return False
    dirpa__Account_Tree_ = dirpa__Account_Tree(dirpa__root)
    dirpa__home = Database.dirp__account_data(dirpa__Account_Tree_) / account["name"]
    dirpa__held = dirpa__Account_Tree_ / DIRN__DEALLOCATED
    name__held = account["name"] + "." + time.strftime("%Y%m%dT%H%M%SZ" ,time.gmtime())

    import Sound   # here, as Sound imports this module
    login = Sound.login__of(storage_db ,account)
    StoragePlug.process__end([row["system_uid"]] ,log ,preview)
    if not Sound.fifo__remove(name ,log ,preview): return False
    if not SameAccount.same_account__end(row ,system_db ,dirpa__Account_Tree_ ,account["name"] ,log ,preview): return False
    SameAccount.local_file__delete(row["system_uid"] ,name ,log ,preview)

    if not dirpa__held.is_dir():
      if not act(log ,preview ,str(dirpa__held) ,os.mkdir ,dirpa__held ,0o700): return False
      if not act(log ,preview ,str(dirpa__held) ,os.chmod ,dirpa__held ,0o700): return False
      log.line("made" ,str(dirpa__held) ,"owned by root, mode 0700; only the administrator removes what it holds")
    if dirpa__home.is_dir():
      if not act(log ,preview ,str(dirpa__home) ,os.rename ,dirpa__home ,dirpa__held / name__held): return False
      log.line("moved" ,str(dirpa__home) ,f"to {dirpa__held / name__held}")
    else:
      log.line("skipped" ,str(dirpa__home) ,"no such directory, so no home is kept")
    with storage_db.transaction(f"deallocate {account['name']}, its row renamed {name__held}" ,preview) as t:
      t.execute("UPDATE account SET state = 'deallocated' ,name = ? ,changed = ? WHERE database_uid = ?"
                ,(name__held ,Database.now() ,account["database_uid"]))
      t.execute("UPDATE database_uid SET state = 'retired' WHERE database_uid = ?" ,(account["database_uid"],))
      t.execute("DELETE FROM account_setting WHERE database_uid = ?" ,(account["database_uid"],))
      t.execute("DELETE FROM account_share WHERE share__database_uid = ? OR member__database_uid = ?"
                ,(account["database_uid"] ,account["database_uid"]))
      Sound.account__forget(t ,account)
    log.line("deallocated" ,name ,f"database uid {account['database_uid']} and system uid {row['system_uid']} retired")
    if login is not None:
      Sound.router__reload(Sound.system_name__of(system_db ,storage_db.uuid() ,login) ,log ,preview)
    return True
