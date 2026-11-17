# -*- mode: python; coding: utf-8; python-indent-offset: 2; indent-tabs-mode: nil -*-
"""
Request·Record - what the request guard reads of the account tree, from the
system database and the storage databases, opened read-only.

The guard decides from the records, never from names: an account is below
another when the parent links of its storage database lead up to it. The
databases are opened with SQLite's mode=ro, so the guard can change nothing,
and nothing the schema adds on opening, as Database.Database.open does, runs.

  RecordError                  a record cannot be read
  open__read_only              a database, read-only
  system_map__in_use           the system map row of a system account in use
  storage_database__of         the storage database of a database uuid, read-only,
                               found where it is mounted
  is__below                    whether one storage account is below another,
                               and why not
  account__below               the checks the request guard makes of an account
                               a request names, below the asking account
"""

import os ,pwd ,sqlite3
from pathlib import Path

import Database
import Kernel
from Common import DIRPA__HOME ,dirpa__Account_Tree
import SystemAccount as sa

DEPTH_MAX = 64   # no tree is deeper; a longer chain of parent links is a loop


class RecordError(Exception):
  """A record cannot be read."""


def open__read_only(filep__database):
  """
  The database at filep__database opened read-only, its rows as
  sqlite3.Row. Raises RecordError.
  """
  filep__database = Path(filep__database)
  if not filep__database.is_file():
    raise RecordError(f"no database at {filep__database}")
  try:
    connection = sqlite3.connect(filep__database.resolve().as_uri() + "?mode=ro" ,uri=True)
    connection.row_factory = sqlite3.Row
    connection.execute("SELECT 1 FROM identity").fetchone()
  except sqlite3.Error as error:
    raise RecordError(f"{filep__database}: {error}")
  return connection

def open__system():
  return open__read_only(Database.FPA__SYSTEM_DATABASE)

def system_map__in_use(system_db ,system_account__name):
  "the system map row in use for the system account, or None"
  return system_db.execute("SELECT * FROM system_map WHERE system_account__name = ? AND state = 'in use'"
                           ,(system_account__name,)).fetchone()

def storage_database__of(system_db ,database_uuid):
  """
  The storage database whose database uuid is database_uuid, read-only, and
  the root of the storage it is on. It is looked for at the mount point of
  each registered removable storage carrying it, and at /, the disk the
  system runs from. Raises RecordError when it is in none of them.
  """
  list__dirpa__root = [Path(r["dirpa__mount"]) for r in system_db.execute(
    "SELECT dirpa__mount FROM storage_device WHERE database_uuid = ? AND state = 'registered'" ,(database_uuid,))]
  list__dirpa__root.append(Path("/"))
  for dirpa__root in list__dirpa__root:
    if dirpa__root != Path("/") and not Kernel.is__mount_point(dirpa__root):
      continue
    filep__database = Database.fpa__storage_database(dirpa__Account_Tree(dirpa__root))
    if not filep__database.is_file():
      continue
    storage_db = open__read_only(filep__database)
    row = storage_db.execute("SELECT database_uuid FROM identity").fetchone()
    if row is not None and row["database_uuid"] == database_uuid:
      return storage_db ,dirpa__root
    storage_db.close()
  raise RecordError(f"the storage database {database_uuid} is not found on any storage attached here")

def is__below(storage_db ,database_uid ,database_uid__above):
  """
  (True ,None) when the storage account database_uid is below the storage
  account database_uid__above in storage_db, by the parent links of the
  database; otherwise (False ,why). An account is not below itself. A chain
  that leaves the database, a parent named but not carried here, is not
  followed: in this version a request reaches only accounts whose parents
  are all carried by one storage database.
  """
  each = database_uid
  for _ in range(DEPTH_MAX):
    row = storage_db.execute("SELECT * FROM account WHERE database_uid = ?" ,(each,)).fetchone()
    if row is None:
      return False ,f"the storage database has no account of database uid {each}"
    parent = row["parent__database_uid"]
    if parent is None:
      if row["parent_name"] is None:
        return False ,f"{row['name']} is a child of root, and the chain above it does not pass the asking account"
      return False ,(f"the parent of {row['name']}, {row['parent_name']}, is kept on another storage;"
                     " a request reaches only accounts whose parents are on the same storage")
    if parent == database_uid__above:
      return True ,None
    each = parent
  return False ,f"the parent links above database uid {database_uid} are longer than {DEPTH_MAX}, a loop"

def account__below(system_db ,account__asking ,account__named):
  """
  The problems, as a list of messages, with a request by the system account
  account__asking that names the system account account__named. Empty when
  account__named is below account__asking in the tree, both are managed by
  Account-Tree and in use here, the named one is active, the system map
  agrees with /etc/passwd about its uid, and its home is mounted.
  """
  if account__named == account__asking:
    return [f"{account__named} is the asking account itself, not an account below it"]
  row__asking = system_map__in_use(system_db ,account__asking)
  if row__asking is None:
    return [f"the asking account {account__asking} is not an account Account-Tree keeps in use here"]
  row__named = system_map__in_use(system_db ,account__named)
  if row__named is None:
    return [f"{account__named} is not an account Account-Tree keeps in use here"]
  if row__named["database_uuid"] != row__asking["database_uuid"]:
    return [f"{account__named} is kept on another storage than {account__asking};"
            " a request reaches only accounts on the asking account's storage"]
  entry = sa.system_account(account__named)
  if entry is None or entry.pw_uid != row__named["system_uid"]:
    return [f"the system map gives {account__named} the system uid {row__named['system_uid']}, and /etc/passwd does not"]
  try:
    storage_db ,_ = storage_database__of(system_db ,row__named["database_uuid"])
  except RecordError as error:
    return [str(error)]
  try:
    state = storage_db.execute("SELECT state FROM account WHERE database_uid = ?" ,(row__named["database_uid"],)).fetchone()
    if state is None or state["state"] != "active":
      return [f"{account__named} is {state['state'] if state else 'not'} in its storage database, not active"]
    below ,why = is__below(storage_db ,row__named["database_uid"] ,row__asking["database_uid"])
    if not below:
      return [f"{account__named} is not below {account__asking}: {why}"]
  finally:
    storage_db.close()
  if not Kernel.is__mount_point(DIRPA__HOME / account__named):
    return [f"the home of {account__named}, {DIRPA__HOME / account__named}, is not mounted"]
  return []
