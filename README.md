Modified https://github.com/XeroAPI/xero-python-oauth2-starter for downloading expense claims receipts attachments.

Note that files are only available via [Files API](https://developer.xero.com/documentation/api/files/files).
[Attachements API](https://developer.xero.com/documentation/api/accounting/attachments) is misleading as per Xero dev support email below:

```text
Date: Mon, 30 Jun 2025 08:37:26 +0000 (GMT)
From: Xero Support <api@support.xero.com>
To: "Ivan" <ivan@odd-e.com>
Subject: Xero Support - Xero API Support: receipts attachments -
-----

The attachments endpoint was created after the deprecation of the expenses endpoint and so expenses were not included in the scope of the GET or PUT/POST requests for attachments.

I have done some testing with API Explorer and an old test account that still has expenses and I was able to use the Files API to get files from Xero and these included files attached to expense claims.
```
