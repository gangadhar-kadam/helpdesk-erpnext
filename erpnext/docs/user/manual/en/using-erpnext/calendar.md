The Calendar is a tool where you can create and share Events and also see
auto-generated events from the system.

You can switch calender view based on Month, Week and Day.

###Creating Events in Calender

####Creating Event Manually

To create event manually, you should first determine Calender View. If Event's start and end time will be within one day, then you should first switch to Day view.

This view will 24 hours of a day broken in various slots. You should click on slot for Event Start Time, and drag it down till you reach event end time.

![Calender Event Manually]({{docs_base_url}}/assets/old_images/erpnext/calender-event-manually.png)

Based on the selection of time slot, Start Time and End Time will be updated in the Event master. Then you can set subject for an event, and save it.

####Event Based on Lead

In the Lead form, you will find a field called Next Contact By and Next Contact Date. Event will be auto created for date and person person specified in this field.

![Calender Event Lead]({{docs_base_url}}/assets/old_images/erpnext/calender-event-lead.png)

####Birthday Event

Birthday Event is created based on Date of Birth specified in the Employee master.

###Recurring Events

You can set events as recurring in specific interval by Checking the "Repeat This
Event".

![Calender Event Recurring]({{docs_base_url}}/assets/old_images/erpnext/calender-event-recurring.png)

###Permission for Event

You can set Event as Private or Public. Private Events will be visible only to you, and if any other user selected in the participants table. Instead of User, you can also assign permission for event based on Role.

Public Event, like Birthday will be visible to all.

![Calender Event Permission]({{docs_base_url}}/assets/old_images/erpnext/calender-event-permission.png)

###Event Reminders

There are two ways you can receive email reminder for an event.

####Enable Reminder in Event

In the Event master, checking "Send an email reminder in the morning" will trigger notifcation email to all the participants for this event.

![Calender Event Notification]({{docs_base_url}}/assets/old_images/erpnext/calender-event-notification.png)

####Create Email Digest

To get email reminders for event, you should set Email Digest for Calender Events.

Email Digest can be set from:

`Setup > Email > Email Digest`

![Calender Email Digest]({{docs_base_url}}/assets/old_images/erpnext/calender-email-digest.png)

{next}
