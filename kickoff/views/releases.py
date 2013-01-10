from flask import request, jsonify, render_template, Response, redirect, make_response, abort
from flask.views import MethodView

from kickoff import db
from kickoff.log import cef_event, CEF_WARN, CEF_INFO
from kickoff.model import getReleaseTable, getReleases
from kickoff.views.forms import CompleteForm, ReadyForm, getReleaseForm

def sortedReleases():
    def cmpReleases(x, y):
        # Not ready releases should come before ready ones.
        # Incomplete releases should come before completed ones.
        # After that, sort by name.
        if x.ready:
            if not y.ready:
                return 1
        elif y.ready:
            return -1
        if x.complete:
            if not y.complete:
                return 1
        elif y.complete:
            return -1
        return cmp(x.name, y.name)
    return sorted(getReleases(), cmp=cmpReleases)

class ReleasesAPI(MethodView):
    def get(self):
        # We can't get request.args to convert directly to a bool because
        # it will convert even if the arg isn't present! In these cases
        # we need to be able to pass along a None, so we must be a bit
        # roundabout here.
        try:
            ready = request.args.get('ready', type=int)
            complete = request.args.get('complete', type=int)
            if ready is not None:
                ready = bool(ready)
            if complete is not None:
                complete = bool(complete)
        except ValueError:
            cef_event('User Input Failed', CEF_INFO, ready=ready, complete=complete)
            return Response(status=400, response="Got unparseable value for ready or complete")
        releases = [r.name for r in getReleases(ready, complete)]
        return jsonify({'releases': releases})

class ReleaseAPI(MethodView):
    def get(self, releaseName):
        table = getReleaseTable(releaseName)
        return jsonify(table.query.filter_by(name=releaseName).first().toDict())

    def post(self, releaseName):
        table = getReleaseTable(releaseName)
        form = CompleteForm()
        if not form.validate():
            cef_event('User Input Failed', CEF_INFO, **form.errors)
            return Response(status=400, response=form.errors)

        release = table.query.filter_by(name=releaseName).first()
        if form.complete.data:
            release.complete = form.complete.data
        if form.status.data:
            release.status = form.status.data
        db.session.add(release)
        db.session.commit()
        return Response(status=200)

class ReleaseL10nAPI(MethodView):
    def get(self, releaseName):
        table = getReleaseTable(releaseName)
        l10n = table.query.filter_by(name=releaseName).first().l10nChangesets
        return Response(status=200, response=l10n, content_type='text/plain')

class Releases(MethodView):
    def get(self):
        # We should really be creating a Form here and letting it render
        # rather than rendering by hand in the template, but it seems that's
        # not possible without some heavy handed subclassing. For our simple
        # case it's not worthwhile
        # http://stackoverflow.com/questions/8463421/how-to-render-my-select-field-with-wtforms
        #form.readyReleases.choices = [(r.name, r.name) for r in getReleases(ready=False)]
        form = ReadyForm()
        return render_template('releases.html', releases=sortedReleases(), form=form)

    def post(self):
        form = ReadyForm()
        form.readyReleases.choices = [(r.name, r.name) for r in getReleases(ready=False)]
        # Don't include completed or ready releases, because they aren't allowed to be deleted
        form.deleteReleases.choices = [(r.name, r.name) for r in getReleases(complete=False, ready=False)]
        if not form.validate():
            cef_event('User Input Failed', CEF_WARN, **form.errors)
            return make_response(render_template('releases.html', errors=form.errors, releases=sortedReleases(), form=form), 400)

        for release in form.deleteReleases.data:
            table = getReleaseTable(release)
            r = table.query.filter_by(name=release).first()
            db.session.delete(r)
        for release in form.readyReleases.data:
            table = getReleaseTable(release)
            r = table.query.filter_by(name=release).first()
            r.ready = True
            r.status = 'Pending'
            db.session.add(r)
        db.session.commit()
        return render_template('releases.html', releases=sortedReleases(), form=form)

class Release(MethodView):
    def get(self):
        name = request.args.get('name')
        form = getReleaseForm(name)()
        release = getReleaseTable(name).query.filter_by(name=name).first()
        if not release:
            abort(404)
        # If this release is already ready or complete, edits aren't allowed.
        # It would be best to display an error here, but considering that there
        # aren't even links to this page for these releases, redirecting back
        # to the list of release seems OK.
        if release.ready or release.complete:
            return redirect('releases.html')

        # If the release is editable, prepopulate the form with the current
        # values from the database.
        form.updateFromRow(release)
        return render_template('release.html', form=form, release=name)

    def post(self):
        name = request.args.get('name')
        form = getReleaseForm(name)()
        release = getReleaseTable(name).query.filter_by(name=name).first()
        if not release:
            abort(404)
        # Similar to the above, don't allow edits to ready or completed
        # releases. Unless someone has constructed a POST by hand, this code
        # should never be hit.
        if release.ready or release.complete:
            errors = ["Cannot update a release that's been marked as ready or is complete"]
            return make_response(render_template('release.html', errors=errors, form=form, release=name), 403)

        if not form.validate():
            return make_response(render_template('release.html', errors=form.errors.values(), form=form, release=name), 400)

        release.updateFromForm(form)
        db.session.add(release)
        db.session.commit()
        return redirect('releases.html')