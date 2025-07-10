# -*- coding: utf-8 -*-
import datetime
import os
from functools import wraps
from io import BytesIO
from logging.config import dictConfig

from flask import Flask, url_for, render_template, session, redirect, json, send_file
from flask_oauthlib.contrib.client import OAuth, OAuth2Application
from flask_session import Session
from xero_python.accounting import AccountingApi, ContactPerson, Contact, Contacts
from xero_python.file import FilesApi
from xero_python.api_client import ApiClient, serialize
from xero_python.api_client.configuration import Configuration
from xero_python.api_client.oauth2 import OAuth2Token
from xero_python.exceptions import AccountingBadRequestException
from xero_python.identity import IdentityApi
from xero_python.utils import getvalue

import logging_settings
from utils import jsonify, serialize_model, invoice_file_name, savepkl

dictConfig(logging_settings.default_settings)

# configure main flask application
app = Flask(__name__)
app.config.from_object("default_settings")
app.config.from_pyfile("config.py", silent=True)

if app.config["ENV"] != "production":
    # allow oauth2 loop to run over http (used for local testing only)
    os.environ["OAUTHLIB_INSECURE_TRANSPORT"] = "1"

# configure persistent session cache
Session(app)

# configure flask-oauthlib application
# TODO fetch config from https://identity.xero.com/.well-known/openid-configuration #1
oauth = OAuth(app)
xero = oauth.remote_app(
    name="xero",
    version="2",
    client_id=app.config["CLIENT_ID"],
    client_secret=app.config["CLIENT_SECRET"],
    endpoint_url="https://api.xero.com/",
    authorization_url="https://login.xero.com/identity/connect/authorize",
    access_token_url="https://identity.xero.com/connect/token",
    refresh_token_url="https://identity.xero.com/connect/token",
    scope="offline_access openid profile email accounting.transactions accounting.transactions.read "
    "accounting.journals.read accounting.transactions payroll.payruns accounting.reports.read "
    "files accounting.settings.read accounting.settings accounting.attachments payroll.payslip payroll.settings files.read openid assets.read profile payroll.employees projects.read email accounting.contacts.read accounting.attachments.read projects assets accounting.contacts payroll.timesheets accounting.budgets.read",
)  # type: OAuth2Application


# configure xero-python sdk client
api_client = ApiClient(
    Configuration(
        debug=app.config["DEBUG"],
        oauth2_token=OAuth2Token(
            client_id=app.config["CLIENT_ID"], client_secret=app.config["CLIENT_SECRET"]
        ),
    ),
    pool_threads=1,
)


# configure token persistence and exchange point between flask-oauthlib and xero-python
@xero.tokengetter
@api_client.oauth2_token_getter
def obtain_xero_oauth2_token():
    return session.get("token")


@xero.tokensaver
@api_client.oauth2_token_saver
def store_xero_oauth2_token(token):
    session["token"] = token
    session.modified = True


def xero_token_required(function):
    @wraps(function)
    def decorator(*args, **kwargs):
        xero_token = obtain_xero_oauth2_token()
        if not xero_token:
            return redirect(url_for("login", _external=True))

        return function(*args, **kwargs)

    return decorator


@app.route("/")
def index():
    xero_access = dict(obtain_xero_oauth2_token() or {})
    return render_template(
        "code.html",
        title="Home | oauth token",
        code=json.dumps(xero_access, sort_keys=True, indent=4),
    )


@app.route("/invoices")
@xero_token_required
def get_invoices():
    xero_tenant_id = get_xero_tenant_id()
    accounting_api = AccountingApi(api_client)
    invoices = []
    for page in range(1, 8):
        print(f"=== Processing {page} ===")
        resp = accounting_api.get_invoices(
            xero_tenant_id, 
            if_modified_since=datetime.datetime(2019, 1, 1),
            statuses=["PAID"],
            order='InvoiceNumber DESC',
            page=page,
            page_size=100,
            include_archived="True",
        )
        for invoice in resp.invoices:
            if invoice.fully_paid_on_date < datetime.date(2019, 1, 1):
                break
            if invoice.type != "ACCREC":
                continue
            try:
                tmp_file = accounting_api.get_invoice_as_pdf(xero_tenant_id, invoice.invoice_id)
                dest_file = invoice_file_name(invoice)
                os.rename(tmp_file, 'invoices/'+dest_file)
                invoices.append(invoice)
            except Exception as e:
                print(f"*** Error processing Invoice ID: {invoice.invoice_id}")
    savepkl("invoices.pkl", invoices)
    code = serialize_model(invoices)
    sub_title = "Total invoices found: {}".format(len(invoices))

    return render_template(
        "code.html", title="Invoices", code=code, sub_title=sub_title
    )


@app.route("/expenses")
@xero_token_required
def get_expenses():
    xero_tenant_id = get_xero_tenant_id()
    accounting_api = AccountingApi(api_client)

    expenses = accounting_api.get_expense_claims(
        xero_tenant_id, 
        if_modified_since=datetime.datetime(2024, 1, 1),
        where='Status=="PAID"',
    )
        
    code = serialize_model(expenses)
    sub_title = "Total expenses found: {}".format(len(expenses.expense_claims))

    return render_template(
        "code.html", title="Expenses", code=code, sub_title=sub_title
    )


@app.route("/receipts")
@xero_token_required
def get_receipts():
    "Download receipt files (attachments) from 2020 to 2024 using Files API !"
    xero_tenant_id = get_xero_tenant_id()
    api = FilesApi(api_client)

    count = 1
    pagesize = 100 
    for page in range(1, 25):  # page 1 == most recent files; 25 is the page that starts to have files from 2019
        all_files = api.get_files(xero_tenant_id, pagesize=pagesize, page=page)

        for idx, file in enumerate(all_files.items):
            created = datetime.datetime.fromisoformat(file.created_date_utc)
            if created.year < 2020:
                break
            try:
                assoc = api.get_file_associations(xero_tenant_id, file.id)[0]
                if assoc.object_type.name != 'RECEIPT':
                    continue
                tmp_file = api.get_file_content(xero_tenant_id, file.id)  # get_file_content returns temp file name of the downloaded data
                owner = file.user.full_name.replace(" ", "-")
                dest_file_name = f"{created.strftime("%Y-%m-%d")}_{owner}_{assoc.object_id}_{file.name}".replace(" ", "_")
                os.rename(tmp_file, 'receipts/'+dest_file_name)
                count += 1
            except Exception as error:
                print(f"*** ERROR processing file #{idx} on page {page} with ID {file.id}\n{error}")

    sub_title = "Download Receipts"
    info = {"total_files": count}

    return render_template(
        "code.html", title="Receipts", code=info, sub_title=sub_title
    )

@app.route("/bills")
@xero_token_required
def get_bills():
    "Download bills attachments from 2020 to 2024 using Files API !"
    xero_tenant_id = get_xero_tenant_id()
    api = FilesApi(api_client)

    count = 1
    pagesize = 100 
    for page in range(1, 26):  # page 1 == most recent files; 25 is the page that starts to have files from 2019
        print(f"Processing page {page}")
        all_files = api.get_files(xero_tenant_id, pagesize=pagesize, page=page)

        for idx, file in enumerate(all_files.items):
            created = datetime.datetime.fromisoformat(file.created_date_utc)
            if created.year < 2020:
                break
            try:
                assoc = api.get_file_associations(xero_tenant_id, file.id)[0]
                if assoc.object_type.name not in ("ACCPAY", "CASHPAID"):
                    continue
                tmp_file = api.get_file_content(xero_tenant_id, file.id)
                dest_file_name = f"{created.strftime("%Y-%m-%d")}_{file.name}".replace(" ", "_")
                os.rename(tmp_file, 'bills/'+dest_file_name)
                count += 1
            except Exception as error:
                print(f"*** ERROR processing file #{idx} on page {page} with ID {file.id}\n{error}")

    sub_title = "Download Bills"
    info = {"total_files": count}

    return render_template(
        "code.html", title="Bills", code=info, sub_title=sub_title
    )


@app.route("/login")
def login():
    redirect_url = url_for("oauth_callback", _external=True)
    response = xero.authorize(callback_uri=redirect_url)
    return response


@app.route("/callback")
def oauth_callback():
    try:
        response = xero.authorized_response()
    except Exception as e:
        print(e)
        raise
    # todo validate state value
    if response is None or response.get("access_token") is None:
        return "Access denied: response=%s" % response
    store_xero_oauth2_token(response)
    return redirect(url_for("index", _external=True))


@app.route("/logout")
def logout():
    store_xero_oauth2_token(None)
    return redirect(url_for("index", _external=True))


@app.route("/export-token")
@xero_token_required
def export_token():
    token = obtain_xero_oauth2_token()
    buffer = BytesIO("token={!r}".format(token).encode("utf-8"))
    buffer.seek(0)
    return send_file(
        buffer,
        mimetype="x.python",
        as_attachment=True,
        attachment_filename="oauth2_token.py",
    )


@app.route("/refresh-token")
@xero_token_required
def refresh_token():
    xero_token = obtain_xero_oauth2_token()
    new_token = api_client.refresh_oauth2_token()
    return render_template(
        "code.html",
        title="Xero OAuth2 token",
        code=jsonify({"Old Token": xero_token, "New token": new_token}),
        sub_title="token refreshed",
    )


def get_xero_tenant_id():
    token = obtain_xero_oauth2_token()
    if not token:
        return None

    identity_api = IdentityApi(api_client)
    for connection in identity_api.get_connections():
        if connection.tenant_type == "ORGANISATION":
            return connection.tenant_id


if __name__ == '__main__':
    app.run(host='localhost', port=5001)
