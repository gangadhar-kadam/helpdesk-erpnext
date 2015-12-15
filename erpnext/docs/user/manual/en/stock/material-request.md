A Material Request is a simple document identifying a requirement of a set of
Items (products or services) for a particular reason.

![Workflow]({{docs_base_url}}/assets/old_images/erpnext/material-request-workflow.jpg)

To generate a Material Request manually go to:

> Stock > Documents > Material Request > New

#### Creating Material Request 

<img class="screenshot" alt="Material Request" src="{{docs_base_url}}/assets/img/buying/material-request.png">

A Material Request can be generated:

  * Automatically from a Sales Order.
  * Automatically when the Projected Quantity of an Item in stores reaches a particular level.
  * Automatically from your Bill of Materials if you use Production Plan to plan your manufacturing activities.
  * If your Items are inventory items, you must also mention the Warehouse where you expect these Items to be delivered. This helps to keep track of the [Projected Quantity]({{docs_base_url}}/user/manual/en/stock/projected-quantity.html) for this Item.

A Material Request can be of type:

* Purchase - If the request material is to be purchased.
* Material Transfer - If the requested material is to be shifted from one warehouse to another.
* Material Issue - If the requested material is to be Issued.

> Info: Material Request is not mandatory. It is ideal if you have centralized
buying so that you can collect this information from various departments.

{next}
