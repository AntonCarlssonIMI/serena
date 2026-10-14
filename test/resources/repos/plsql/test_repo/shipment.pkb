create or replace package body Shipment as

  procedure Ship_Order(p_order_id in number) is
    l_order Order_Mgmt.t_order_rec;
  begin
    if Order_Mgmt.Read_Order(p_order_id, l_order) then
      Order_Mgmt.Close_Order(p_order_id => p_order_id, p_force => true);
    end if;
    Order_Mgmt.Add_Line(p_order_id, 'SHIPPING');
    if Audit_Log.Entry_Count > 100 then
      null;
    end if;
  end Ship_Order;

end Shipment;
/
