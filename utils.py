# -*- coding: utf-8 -*-
import json
import uuid
from datetime import datetime, date
from decimal import Decimal
import pickle

from xero_python.api_client.serializer import serialize


class JSONEncoder(json.JSONEncoder):
    def default(self, o):
        if isinstance(o, datetime):
            return o.isoformat()
        if isinstance(o, date):
            return o.isoformat()
        if isinstance(o, (uuid.UUID, Decimal)):
            return str(o)
        return super(JSONEncoder, self).default(o)


def parse_json(data):
    return json.loads(data, parse_float=Decimal)


def serialize_model(model):
    return jsonify(serialize(model))


def jsonify(data):
    return json.dumps(data, sort_keys=True, indent=4, cls=JSONEncoder)


def savepkl(filename, data):
    with open(filename, 'wb') as f:
        pickle.dump(data, f)


def loadpkl(filename):
    with open(filename, 'rb') as f:
        data = pickle.load(f)
    return data

def invoice_file_name(invoice):
    date = invoice.date
    paid_date = invoice.fully_paid_on_date
    number = invoice.invoice_number
    amount = str(invoice.amount_paid).split('.')[0]
    return f"{date}_{number}_{paid_date}_{amount}.pdf"