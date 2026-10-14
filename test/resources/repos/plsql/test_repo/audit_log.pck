prompt Don't run this script twice
create or replace package Audit_Log as

  procedure Write_Entry(p_action in varchar2, p_ref_id in number);

  function Entry_Count return number;

end Audit_Log;
/

rem The body's implementation follows
create or replace package body Audit_Log as

  g_count number := 0;

  procedure Write_Entry(p_action in varchar2, p_ref_id in number) is
    l_note varchar2(100) := q'[it's logged; end]';
  begin
    insert into audit_entries (action, ref_id, note)
    values (p_action, p_ref_id, l_note);
    g_count := g_count + 1;
    declare
      entry_count number := g_count;
    begin
      g_count := entry_count;
    end;
    for entry_count in 1 .. 2 loop
      g_count := g_count + entry_count;
    end loop;
  end Write_Entry;

  function Entry_Count return number is
  begin
    return g_count;
  end Entry_Count;

  procedure Reset(p_keep in number) is
    entry_count number := p_keep;
  begin
    g_count := entry_count;
  end Reset;

end Audit_Log;
/
