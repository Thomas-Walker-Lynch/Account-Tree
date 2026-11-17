/*
  Account_Tree__Gate·Request - the gate of Account-Tree's request language:
  Man-In-Grey's general gate with the language name and the guard's and
  interpreter's paths fixed.

  A person's Account-Tree program composes a journal of one request, such as
  entering a child account, and invokes this gate with it. Installed by
  Account-Tree_install setuid root, in /usr/local/lib/Account-Tree/Account_Tree__Gate/,
  so that the guard and the interpreter, Request·Guard.py and
  Request·Interpreter.py in the directory above, run with root's rights,
  while the gate's real uid tells them, from the kernel, which account asked.

  Gate.lib.c and libMan_In_Grey.a come from Man-In-Grey's promoted
  consumer/Man_In_Grey__Gate/, through Account_Tree__Gate.mk.
*/
#include "Gate.lib.c"

int main(int argc ,char **argv){
  return Man_In_Grey__Gate·Gate·run("Request" ,"../Request·Guard.py" ,"../Request·Interpreter.py" ,argc ,argv);
}
