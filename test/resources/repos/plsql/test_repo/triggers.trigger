create or replace trigger Orders_Audit_Trg
  after insert or update on orders
  for each row
begin
  Audit_Log.Write_Entry('ORDERS', :new.order_id);
end;
/

create or replace trigger Order_Lines_Check_Trg
  before insert on order_lines
  for each row
declare
  l_order Order_Mgmt.t_order_rec;
begin
  if not Order_Mgmt.Read_Order(:new.order_id, l_order) then
    raise_application_error(-20001, 'Unknown order');
  end if;
end;
/
