Production Planning Tool helps you plan production and purchase of Items for a
period (usually a week or a month).

This list of Items can be generated from the open Sales Orders in the system
and will generate:

  * Production Orders for each Item.
  * Purchase Requests for Items whose Projected Quantity is likely to fall below zero.

To use the Production Planning Tool, go to:

> Manufacturing > Tools > Production Planning Tool

<img class="screenshot" alt="Production Planing Tool" src="{{docs_base_url}}/assets/img/manufacturing/ppt.png">



#### Step 1: Select and get Sales Order

* Select sales orders for MRP using filters (Time, Item, and Customer)
* Click on Get Sales Order to generate a list.

<img class="screenshot" alt="Production Planing Tool" src="{{docs_base_url}}/assets/img/manufacturing/ppt-get-sales-orders.png">



#### Step 2: Get Item from Sales Orders.

You can add/remove or change quantity of these Items.

<img class="screenshot" alt="Production Planing Tool" src="{{docs_base_url}}/assets/img/manufacturing/ppt-get-item.png">

#### Step 3: Create Production Orders

<img class="screenshot" alt="Production Planing Tool" src="{{docs_base_url}}/assets/img/manufacturing/ppt-create-production-order.png">



#### Step 4: Create Material Request

Create Material Request for Items with projected shortfall.

<img class="screenshot" alt="Production Planing Tool" src="{{docs_base_url}}/assets/img/manufacturing/ppt-create-material-request.png">



The Production Planning Tool is used in two stages:

  * Selection of Open Sales Orders for the period based on “Expected Delivery Date”.
  * Selection of Items from those Sales Orders.

The tool will update if you have already created Production Orders for a
particular Item against its Sales Order (“Planned Quantity”).

You can always edit the Item list and increase / reduce quantities to plan
your production.

> Note: How do you change a Production Plan? The output of the Production
Planning Tool is the Production Order. Once your orders are created, you can
change them by amending the Production Orders.

{next}
