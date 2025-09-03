from flask_sqlalchemy import SQLAlchemy

db = SQLAlchemy()

class Catalog(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    hidden = db.Column(db.Boolean, default=False)
    pages = db.relationship('Page', backref='catalog', cascade="all, delete-orphan")

class Page(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(150), nullable=False)
    content = db.Column(db.Text, nullable=True)
    catalog_id = db.Column(db.Integer, db.ForeignKey('catalog.id'))
    hidden = db.Column(db.Boolean, default=False)
