from flask import Blueprint

hrms_bp = Blueprint(
    'hrms',
    __name__,
    url_prefix='/hrms'
)
