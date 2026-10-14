create or replace package body Legacy_Broken as

  procedure Never_Closed is
  begin
    if true then
      null;
    -- the matching "end if;" and "end Never_Closed;" are missing
end Legacy_Broken;
/

create or replace package Recovered_Pkg as
  procedure Still_Found;
end Recovered_Pkg;
/
