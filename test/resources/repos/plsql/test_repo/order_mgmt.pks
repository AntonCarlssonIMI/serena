-- Public API for orders.
-- procedure Not_A_Symbol(p_x in number);
create or replace package Order_Mgmt as

  /* function Also_Not_A_Symbol return number; */
  c_max_lines constant pls_integer := 100;

  e_order_locked exception;

  type t_order_rec is record (
    order_id number,
    status   varchar2(10)
  );

  type t_order_tab is table of t_order_rec index by pls_integer;

  function Read_Order(p_order_id in number, p_order_o out t_order_rec) return boolean;

  procedure Add_Line(p_order_id in number, p_item in varchar2);

  procedure Add_Line(p_order_id in number, p_item in varchar2, p_qty in number);

  procedure Close_Order(p_order_id in number, p_force in boolean default false);

end Order_Mgmt;
/
