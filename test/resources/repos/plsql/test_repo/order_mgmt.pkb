create or replace package body Order_Mgmt as

  g_last_order number;

  cursor c_lines(p_order_id number) is
    select line_no, item
      from order_lines
     where order_id = p_order_id;

  function Read_Order(p_order_id in number, p_order_o out t_order_rec) return boolean is
  begin
    select order_id, status
      into p_order_o
      from orders
     where order_id = p_order_id;
    g_last_order := p_order_id;
    return true;
  exception
    when no_data_found then
      return false;
  end Read_Order;

  procedure Add_Line(p_order_id in number, p_item in varchar2) is
  begin
    Add_Line(p_order_id, p_item, 1);
  end Add_Line;

  procedure Add_Line(p_order_id in number, p_item in varchar2, p_qty in number) is
    l_order t_order_rec;
  begin
    if not Read_Order(p_order_id, l_order) then
      raise e_order_locked;
    end if;
    insert into order_lines (order_id, item, qty)
    values (p_order_id, p_item, p_qty);
    Audit_Log.Write_Entry('Add_Line', p_order_id);
  end Add_Line;

  procedure Close_Order(p_order_id in number, p_force in boolean default false) is
    l_count pls_integer := 0;

    procedure Mark_Closed(p_id in number) is
    begin
      update orders set status = 'CLOSED; end' where order_id = p_id;
    end Mark_Closed;

  begin
    for r in c_lines(p_order_id) loop
      l_count := l_count + 1;
      case
        when l_count > c_max_lines then
          exit;
        else
          null;
      end case;
    end loop;
    if p_force or l_count = 0 then
      Mark_Closed(p_order_id);
    end if;
    Audit_Log.Write_Entry(case when p_force then 'Force' else 'Close' end, p_order_id);
  end Close_Order;

end Order_Mgmt;
/
show errors
