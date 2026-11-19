# -*- mode: python; coding: utf-8; python-indent-offset: 2; indent-tabs-mode: nil -*-
"""
Request·Language - the language definition of Request, the instruction
language a person's Account-Tree program gives the request gate in.

Data only; see Man-In-Grey's Language.py for its form. Each instruction is a
request, named for the work it asks for, so the guard can check it against
who asked and what the account tree allows. A journal holds one request.

  enter(account_name ,display ,terminal_type ,>session)
                       start a login session of account_name, a child account
                       below the account that asked, on a new terminal, and
                       write the terminal to session. display names the
                       asking account's display, for the child to open
                       windows on; each of its texts is empty where there is
                       none. terminal_type is the TERM the session is given.
                       session holds the terminal's master side, a
                       descriptor, which the asking program relays its own
                       terminal to.
  make_child_account(account_name ,>made)
                       make the account account_name, whose parent, the name
                       before its last '·', is the account that asked or an
                       account below it, on the parent's storage, with its
                       home mounted, and write its name and uids to made
  deallocate(account_name)
                       remove account_name, an account below the one that
                       asked with none below it: its processes are ended, its
                       system account goes, its uids are retired, and its home
                       is moved into account-deallocated/ on its storage
  share_with(account_name ,list__account_name)
                       share account_name with each account of the list: each
                       becomes a member of account_name's own group, on every
                       system the storage is attached to
  share_remove(account_name ,list__account_name)
                       end those shares
  sound_show(account_name ,>sound)
                       what the window shows of account_name's sound: its
                       tree's buses with the accounts holding each end, the
                       marks of the permits of account_name and its child
                       accounts, and account_name's connection table
  sound_permit_issue(account_name ,permit)
  sound_permit_revoke(account_name ,permit)
                       issue account_name a permit, or revoke it: for a bus
                       end, as 1.gather or 2.broadcast, or a device, @output
                       or @input
  sound_connection_set(account_name ,text__connection)
                       replace account_name's connection table with the text
  sound_connection_reset(account_name)
                       put account_name's default connection table back
  sound_bus_set(bus__number ,bus__name)
                       make or rename a bus of the asking account's tree, the
                       asking account being its login account
  sound_bus_remove(bus__number)
                       remove a bus no connection table names
  sound_route_show(>route)
                       what the asking account's router is to do: its program
                       lines in force and its FIFOs, or, for the login
                       account, every FIFO of the tree and the device
                       connections in force
"""

NAME = "Request"

DEFINITION = {
  "list__type": [
    ["account_name" ,"text"]
    ,["display" ,["dictionary"
                  ,["display" ,"text"]            # DISPLAY, as :0, for X programs; empty for none
                  ,["wayland_display" ,"text"]    # the Wayland socket's absolute path; empty for none
                  ,["xauthority" ,"text"]]]       # the X authority file's absolute path; empty for none
    ,["terminal_type" ,"text"]
    ,["session" ,["dictionary" ,["pty" ,"descriptor"]]]
    ,["list__account_name" ,["list" ,"text"]]
    ,["made" ,["dictionary" ,["name" ,"text"] ,["database_uid" ,"integer"] ,["system_uid" ,"integer"]]]
    ,["permit" ,"text"]
    ,["text__connection" ,"text"]
    ,["bus__number" ,"integer"]
    ,["bus__name" ,"text"]
    ,["sound_bus" ,["dictionary" ,["number" ,"integer"] ,["name" ,"text"]
                    ,["list__gather" ,["list" ,"text"]] ,["list__broadcast" ,["list" ,"text"]]]]
    ,["sound_device" ,["dictionary" ,["device" ,"text"] ,["list__holder" ,["list" ,"text"]]]]
    ,["sound_mark" ,["dictionary" ,["permit" ,"text"] ,["mark" ,"text"]]]
    ,["sound_row" ,["dictionary" ,["name" ,"text"] ,["list__mark" ,["list" ,"sound_mark"]]]]
    ,["sound" ,["dictionary" ,["login" ,"text"] ,["has__grant" ,"boolean"] ,["is__configured" ,"boolean"]
                ,["list__bus" ,["list" ,"sound_bus"]] ,["list__device" ,["list" ,"sound_device"]]
                ,["list__row" ,["list" ,"sound_row"]] ,["has__table" ,"boolean"] ,["connection" ,"text"]]]
    ,["route_bus" ,["dictionary" ,["number" ,"integer"] ,["name" ,"text"]]]
    ,["route_line" ,["dictionary" ,["end" ,"text"] ,["bus__number" ,"integer"] ,["pattern" ,"text"]]]
    ,["route_fifo" ,["dictionary" ,["account" ,"text"] ,["bus__number" ,"integer"] ,["end" ,"text"] ,["path" ,"text"]]]
    ,["route_device" ,["dictionary" ,["device" ,"text"] ,["bus__number" ,"integer"] ,["end" ,"text"]]]
    ,["route" ,["dictionary" ,["is__hub" ,"boolean"] ,["list__bus" ,["list" ,"route_bus"]]
                ,["list__line" ,["list" ,"route_line"]] ,["list__fifo" ,["list" ,"route_fifo"]]
                ,["list__device" ,["list" ,"route_device"]]]]
  ]
  ,"list__format": [
    ["format__enter" ,["in" ,"account_name"] ,["in" ,"display"] ,["in" ,"terminal_type"] ,["out" ,"session"]]
    ,["format__make_child_account" ,["in" ,"account_name"] ,["out" ,"made"]]
    ,["format__account" ,["in" ,"account_name"]]
    ,["format__share" ,["in" ,"account_name"] ,["in" ,"list__account_name"]]
    ,["format__sound_show" ,["in" ,"account_name"] ,["out" ,"sound"]]
    ,["format__sound_permit" ,["in" ,"account_name"] ,["in" ,"permit"]]
    ,["format__sound_connection_set" ,["in" ,"account_name"] ,["in" ,"text__connection"]]
    ,["format__sound_bus_set" ,["in" ,"bus__number"] ,["in" ,"bus__name"]]
    ,["format__sound_bus_remove" ,["in" ,"bus__number"]]
    ,["format__sound_route_show" ,["out" ,"route"]]
  ]
  ,"list__result": ["session" ,"made" ,"sound" ,"route"]
  ,"map__instruction": {
    "enter": "format__enter"
    ,"make_child_account": "format__make_child_account"
    ,"deallocate": "format__account"
    ,"share_with": "format__share"
    ,"share_remove": "format__share"
    ,"sound_show": "format__sound_show"
    ,"sound_permit_issue": "format__sound_permit"
    ,"sound_permit_revoke": "format__sound_permit"
    ,"sound_connection_set": "format__sound_connection_set"
    ,"sound_connection_reset": "format__account"
    ,"sound_bus_set": "format__sound_bus_set"
    ,"sound_bus_remove": "format__sound_bus_remove"
    ,"sound_route_show": "format__sound_route_show"
  }
}
