# -*- mode: python; coding: utf-8; python-indent-offset: 2; indent-tabs-mode: nil -*-
"""
Share - one account sharing its files with others on its storage.

A share is kept as group membership: the member account is a supplementary
member of the own group of the sharing account, the group named as the
account is. The member reaches whatever the sharing account gives its
group, by the group bits of its files' modes. Thomas·incommon shares its
library of configuration files this way, with every Thomas account.

The storage database's account_share table records each share, by the two
accounts' database uids, and is the authority: attach makes each share on
the system the storage is attached to, so a share made or removed on one
system holds on every other. A system's saved groups are not used for the
own groups of a storage's accounts; see SameAccount.same_account__replug.

  share__with      record shares and make them on this system
  share__remove    delete shares and undo them on this system
  share__apply     make every share of a storage on this system, for attach
  share__record    record the shares this system has among a storage's
                   accounts, as group memberships made before the table was,
                   so that they are kept

Each is run under root, by Account-Tree_admin or by the request interpreter,
which checks the request against the records first, and takes the lock plug
and unplug take. A work function reports through log; it returns False when
it stops, having logged why.
"""

import Database
import Storage
import StoragePlug
import SystemAccount as sa
from Common import act
from System import open_system_database
import ChildAccount


def is__member(name__member ,name__share):
  "whether the system account name__member is a supplementary member of the group name__share"
  group = sa.system_group(name__share)
  return group is not None and name__member in group.gr_mem

def system_name__of(system_db ,database_uuid ,database_uid):
  "the system account in use here for a storage account, or None"
  row = system_db.row("SELECT system_account__name FROM system_map WHERE database_uuid = ? AND database_uid = ? AND state = 'in use'"
                      ,(database_uuid ,database_uid))
  return row["system_account__name"] if row else None

def share__found(name__share ,list__member ,log):
  """
  (system_db ,storage_db ,row__share ,list__row__member) for a share and its
  members, all in use here and on one storage; None with an error logged.
  """
  found = ChildAccount.account__in_use(name__share ,log)
  if found is None: return None
  system_db ,row__share ,_ ,storage_db ,_ = found
  list__row__member = []
  for name in list__member:
    row = system_db.row("SELECT * FROM system_map WHERE system_account__name = ? AND state = 'in use'" ,(name,))
    if row is None:
      log.error(name ,"not an account Account-Tree keeps in use here"); return None
    if row["database_uuid"] != row__share["database_uuid"]:
      log.error(name ,f"is kept on another storage than {name__share}; a share is between accounts of one storage"); return None
    if row["database_uid"] == row__share["database_uid"]:
      log.error(name ,"an account does not share with itself"); return None
    list__row__member.append(row)
  return system_db ,storage_db ,row__share ,list__row__member

def share__with(name__share ,list__member ,log ,preview):
  """
  Share the account name__share with each account in list__member: record
  each share in the storage database, and make each member a member of
  name__share's group here. Returns True when it was done, or would be.
  """
  with StoragePlug.Lock():
    found = share__found(name__share ,list__member ,log)
    if found is None: return False
    system_db ,storage_db ,row__share ,list__row__member = found
    list__new = [r for r in list__row__member if storage_db.row(
      "SELECT 1 FROM account_share WHERE share__database_uid = ? AND member__database_uid = ?"
      ,(row__share["database_uid"] ,r["database_uid"])) is None]
    for r in list__row__member:
      if r not in list__new:
        log.line("kept" ,f"{name__share} with {r['system_account__name']}" ,"already shared")
    if list__new:
      with storage_db.transaction(f"share {name__share} with " + ", ".join(r["system_account__name"] for r in list__new) ,preview) as t:
        for r in list__new:
          t.execute("INSERT INTO account_share(share__database_uid ,member__database_uid ,made) VALUES (? ,? ,?)"
                    ,(row__share["database_uid"] ,r["database_uid"] ,Database.now()))
    for r in list__row__member:
      member = r["system_account__name"]
      if is__member(member ,name__share): continue
      if not act(log ,preview ,member ,sa.system_account__group_add ,member ,[name__share]): return False
      log.line("shared" ,f"{name__share} with {member}" ,f"{member} is a member of the group {name__share}")
    return True

def share__remove(name__share ,list__member ,log ,preview):
  """
  End the share of name__share with each account in list__member: delete
  each share from the storage database, and take each member out of
  name__share's group here. Returns True when it was done, or would be.
  """
  with StoragePlug.Lock():
    found = share__found(name__share ,list__member ,log)
    if found is None: return False
    system_db ,storage_db ,row__share ,list__row__member = found
    with storage_db.transaction(f"end the share of {name__share} with " + ", ".join(r["system_account__name"] for r in list__row__member) ,preview) as t:
      for r in list__row__member:
        t.execute("DELETE FROM account_share WHERE share__database_uid = ? AND member__database_uid = ?"
                  ,(row__share["database_uid"] ,r["database_uid"]))
    for r in list__row__member:
      member = r["system_account__name"]
      if not is__member(member ,name__share):
        log.line("kept" ,f"{name__share} and {member}" ,"not shared here"); continue
      if not act(log ,preview ,member ,sa.system_account__group_remove ,member ,name__share): return False
      log.line("unshared" ,f"{name__share} from {member}" ,f"{member} is no longer a member of the group {name__share}")
    return True

def share__apply(system_db ,storage_db ,log ,preview):
  """
  Make here every share storage_db records whose two accounts are in use
  here. Run by attach once the storage's system accounts are made.
  """
  database_uuid = storage_db.uuid()
  for s in storage_db.rows("SELECT * FROM account_share ORDER BY share__database_uid ,member__database_uid"):
    share = system_name__of(system_db ,database_uuid ,s["share__database_uid"])
    member = system_name__of(system_db ,database_uuid ,s["member__database_uid"])
    if share is None or member is None or is__member(member ,share): continue
    if act(log ,preview ,member ,sa.system_account__group_add ,member ,[share]):
      log.line("shared" ,f"{share} with {member}" ,"as the storage database records")

def share__record(dirp__storage ,log ,preview):
  """
  Record in the storage database each share this system has among the
  storage's accounts in use here: each membership of one of them in the own
  group of another. For shares made as group memberships before the
  storage database kept them; once recorded, they hold on every system.
  """
  with StoragePlug.Lock():
    system_db = open_system_database(log)
    if system_db is None: return False
    storage_db = Storage.open_storage_database(dirp__storage ,log)
    if storage_db is None: return False
    database_uuid = storage_db.uuid()
    list__row = system_db.rows("SELECT * FROM system_map WHERE database_uuid = ? AND state = 'in use' ORDER BY system_account__name"
                               ,(database_uuid,))
    by_name = {r["system_account__name"]: r for r in list__row}
    list__found = []
    for member in list__row:
      for group in sa.list__supplementary_group(member["system_account__name"]):
        share = by_name.get(group)
        if share is None: continue
        if storage_db.row("SELECT 1 FROM account_share WHERE share__database_uid = ? AND member__database_uid = ?"
                          ,(share["database_uid"] ,member["database_uid"])):
          log.line("kept" ,f"{group} with {member['system_account__name']}" ,"recorded already")
          continue
        list__found.append((share ,member))
    if not list__found:
      log.line("kept" ,str(dirp__storage) ,"no share to record"); return True
    with storage_db.transaction(f"record {len(list__found)} shares this system had as group memberships" ,preview) as t:
      for share ,member in list__found:
        t.execute("INSERT INTO account_share(share__database_uid ,member__database_uid ,made) VALUES (? ,? ,?)"
                  ,(share["database_uid"] ,member["database_uid"] ,Database.now()))
    for share ,member in list__found:
      log.line("recorded" ,f"{share['system_account__name']} with {member['system_account__name']}")
    return True
