"""Tests for the macros.html helpers (render_notif, render_field)."""
from flask_wtf import FlaskForm
from wtforms import StringField
from wtforms.validators import DataRequired


class _DemoForm(FlaskForm):
    name = StringField("Nama", validators=[DataRequired()])


def _render(app, src, **ctx):
    template = app.jinja_env.from_string(src)
    with app.test_request_context():
        return template.render(**ctx)


def test_render_field_shows_invalid_feedback_on_error(app):
    with app.test_request_context():
        form = _DemoForm()
        form.name.data = ""
        form.validate()
    out = _render(
        app,
        '{% from "macros.html" import render_field %}{{ render_field(form.name) }}',
        form=form,
    )
    assert "is-invalid" in out
    assert "invalid-feedback" in out


def test_render_field_clean_has_no_invalid(app):
    with app.test_request_context():
        form = _DemoForm()  # not validated -> no errors
    out = _render(
        app,
        '{% from "macros.html" import render_field %}{{ render_field(form.name) }}',
        form=form,
    )
    assert "is-invalid" not in out
    assert "form-control" in out


def test_render_field_forwards_extra_kwargs(app):
    with app.test_request_context():
        form = _DemoForm()
    out = _render(
        app,
        '{% from "macros.html" import render_field %}'
        '{{ render_field(form.name, autocomplete="username", extra_class="x") }}',
        form=form,
    )
    assert 'autocomplete="username"' in out
    assert "x" in out


def test_render_field_custom_base_class_for_select(app):
    with app.test_request_context():
        form = _DemoForm()
    out = _render(
        app,
        '{% from "macros.html" import render_field %}'
        '{{ render_field(form.name, base_class="form-select") }}',
        form=form,
    )
    assert "form-select" in out
    assert "form-control" not in out


def test_render_notif_renders_each_kind(app):
    out = _render(
        app,
        '{% from "macros.html" import render_notif %}'
        '{{ render_notif("oops", "yay", "fyi") }}',
    )
    assert "alert-warning" in out
    assert "oops" in out
    assert "alert-success" in out
    assert "yay" in out
    assert "alert-primary" in out
    assert "fyi" in out


def test_render_notif_renders_nothing_when_empty(app):
    out = _render(
        app,
        '{% from "macros.html" import render_notif %}{{ render_notif(None, None, None) }}',
    )
    assert "alert" not in out
