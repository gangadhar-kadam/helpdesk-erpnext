# Email Accounts

You can manage multiple incoming and outgoing Email Accounts in ERPNext. There has to be atleast one default outgoing account and one default incoming account. If you are on the ERPNext cloud, the default outgoing email is set by us.

> **Note for self implementers:** For outgoing emails, you should setup your own SMTP server or sign up with an SMTP relay service like mandrill.com or sendgrid.com that allows a larger number of transactional emails to be sent. Regular email services like GMail will restrict you to a limited number of emails per day.

### Default Email Accounts

ERPNext will create templates for a bunch of email accounts by default. Not all of them are enabled. To enable them, you must set your account details.

There are 2 types of email accounts, outgoing and incoming. Outgoing email accounts use an SMTP service to send emails and emails are retrived from your inbox using a POP service. Most email providers such as GMail, Outlook or Yahoo provide these services.

<img class="screenshot" alt="Defining Criteria" src="{{docs_base_url}}/assets/img/setup/email/email-account-list.png">

### Outgoing Email Accounts

All emails sent from the system, either by the user to a contact or notifications or transaction emails, will be sent from an Outgoing Email Account.

To setup an outgoing Email Account, check on **Enable Outgoing** and set your SMTP server settings, if you are using a popular email service, these will be preset for you.

<img class="screenshot" alt="Outgoing EMail" src="{{docs_base_url}}/assets/img/setup/email/email-account-sending.png">

### Incoming Email Accounts

To setup an incoming Email Account, check on **Enable Incoming** and set your POP3 settings, if you are using a popular email service, these will be preset for you.

<img class="screenshot" alt="Incoming EMail" src="{{docs_base_url}}/assets/img/setup/email/email-account-incoming.png">

### How ERPNext handles replies

In ERPNext when you send an email to a contact like a customer, the sender will be the user who sent the email. In the **Reply-To** property, the email id will be of the default incoming account (like `replies@yourcompany.com`). ERPNext will automatically extract these emails from the incoming account and tag it to the relvant communication

### Notification for unreplied messages

If you would like ERPNext to notify you if an email is unreplied for a certain amount of time, then you can set **Notify if Unreplied**. Here you can set the number of minutes to wait before notifications are sent and whom the notifications must go to.

<img class="screenshot" alt="Incoming EMail" src="{{docs_base_url}}/assets/img/setup/email/email-account-unreplied.png">

{next}
