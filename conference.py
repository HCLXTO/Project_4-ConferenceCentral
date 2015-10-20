#!/usr/bin/env python

"""
conference.py -- Udacity conference server-side Python App Engine API;
    uses Google Cloud Endpoints

$Id: conference.py,v 1.25 2014/05/24 23:42:19 wesc Exp wesc $

created by wesc on 2014 apr 21

"""

__author__ = 'wesc+api@google.com (Wesley Chun)'


from datetime import datetime

import endpoints
from protorpc import messages
from protorpc import message_types
from protorpc import remote

from google.appengine.api import memcache
from google.appengine.api import taskqueue
from google.appengine.ext import ndb

import logging  # loggins de erro

from models import ConflictException
from models import Profile
from models import ProfileMiniForm
from models import ProfileForm
from models import StringMessage
from models import BooleanMessage
from models import QueryForm
from models import QueryForms
from models import Conference
from models import ConferenceForm
from models import ConferenceForms
from models import ConferenceQueryForm
from models import ConferenceQueryForms
from models import TeeShirtSize
from models import Session
from models import SessionForm
from models import SessionForms
from models import SessionQueryForm
from models import SessionQueryForms
from models import Speaker
from models import SpeakerForm
from models import SpeakerForms

from settings import WEB_CLIENT_ID
from settings import ANDROID_CLIENT_ID
from settings import IOS_CLIENT_ID
from settings import ANDROID_AUDIENCE

from utils import getUserId

EMAIL_SCOPE = endpoints.EMAIL_SCOPE
API_EXPLORER_CLIENT_ID = endpoints.API_EXPLORER_CLIENT_ID
MEMCACHE_ANNOUNCEMENTS_KEY = "RECENT_ANNOUNCEMENTS"
MEMCACHE_FEATURED_SPEAKER_PRE_KEY = "FeaturedSpeaker|"
ANNOUNCEMENT_TPL = ('Last chance to attend! The following conferences '
                    'are nearly sold out: %s')
# - - - - - - - - - - - - - - - - - - - - - - - - - - - - - -

INEQUALITY_FILTERS = []

DEFAULTS = {
    "city": "Default City",
    "maxAttendees": 0,
    "seatsAvailable": 0,
    "topics": [ "Default", "Topic" ],
}

DEFAULT_SPEAKER = {
    "name": "Default Name",
    "biography": "Default bio",
    "specialty": ["Default specialty"],
    "company": "Default company"
}

OPERATORS = {
            'EQ':   '=',
            'GT':   '>',
            'GTEQ': '>=',
            'LT':   '<',
            'LTEQ': '<=',
            'NE':   '!='
            }

FIELDS =    {
            'CITY': 'city',
            'TOPIC': 'topics',
            'MONTH': 'month',
            'MAX_ATTENDEES': 'maxAttendees',
            }

CONF_GET_REQUEST = endpoints.ResourceContainer(
    message_types.VoidMessage,
    websafeConferenceKey=messages.StringField(1),
)

CONF_POST_REQUEST = endpoints.ResourceContainer(
    ConferenceForm,
    websafeConferenceKey=messages.StringField(1),
)

SESSION_KEY = endpoints.ResourceContainer(
    message_types.VoidMessage,
    websafeSessionKey=messages.StringField(1)
)

SESSION_GET_BY_TYPE_REQUEST = endpoints.ResourceContainer(
    message_types.VoidMessage,
    websafeConferenceKey=messages.StringField(1),
    typeOfSession=messages.StringField(2),
)

SESSION_GET_BY_COMPANY_REQUEST = endpoints.ResourceContainer(
    message_types.VoidMessage,
    websafeConferenceKey=messages.StringField(1),
    company=messages.StringField(2),
)

SESSION_GET_BY_SPECIALTY_REQUEST = endpoints.ResourceContainer(
    message_types.VoidMessage,
    websafeConferenceKey=messages.StringField(1),
    specialty=messages.StringField(2),
)

SESSION_POST_REQUEST = endpoints.ResourceContainer(
    SessionForm,
    websafeConferenceKey=messages.StringField(1),
)

SPEAKER_GET_BY_NAME_REQUEST = endpoints.ResourceContainer(
    message_types.VoidMessage,
    speaker=messages.StringField(1),
)

SPEAKER_POST_REQUEST = endpoints.ResourceContainer(
    SpeakerForm,
)

# - - - - - SuportFunctions - - - - - - - - - - - - - - - - -


def equal(prop, value):
    """Check if a property is equal to a value"""
    return prop == value


def grt(prop, value):
    """Check if a property is greater than a value"""
    return prop > value


def grtEq(prop, value):
    """Check if a property is greater than or equal to a value"""
    return prop >= value


def les(prop, value):
    """Check if a property is less than a value"""
    return prop < value


def lesEq(prop, value):
    """Check if a property is less than or equal to a value"""
    return prop <= value


def notEq(prop, value):
    """Check if a property is different from a value"""
    return prop != value

# Index if the validating function related with every compareting simbol
VALIDATORS = {
            '=':   equal,
            '>':   grt,
            '>=': grtEq,
            '<':   les,
            '<=': lesEq,
            '!=':   notEq
            }


def validadeInequalityFilter(inequality_filters, entity):
    """Check if a entity attends all the inequality filters inputed"""
    check = True
    # Iterated on every the inequality filter informed
    for f in inequality_filters:
        if hasattr(entity, f["field"]):  # Check if the entity has the attribute
            # Check if the entity atends the filter
            if not VALIDATORS[f["operator"]](getattr(entity, f["field"]), f['value']):
                check = False
        else:
            check = False
    return check

# - - - - API - - - - - - - - - - - - - - - - - - - - - - - -


@endpoints.api(name='conference', version='v1', audiences=[ANDROID_AUDIENCE],
    allowed_client_ids=[WEB_CLIENT_ID, API_EXPLORER_CLIENT_ID, ANDROID_CLIENT_ID, IOS_CLIENT_ID],
    scopes=[EMAIL_SCOPE])
class ConferenceApi(remote.Service):
    """Conference API v0.1"""

# - - - Conference objects - - - - - - - - - - - - - - - - -

    def _copyConferenceToForm(self, conf, displayName):
        """Copy relevant fields from Conference to ConferenceForm."""
        cf = ConferenceForm()
        for field in cf.all_fields():
            if hasattr(conf, field.name):
                # convert Date to date string; just copy others
                if field.name.endswith('Date'):
                    setattr(cf, field.name, str(getattr(conf, field.name)))
                else:
                    setattr(cf, field.name, getattr(conf, field.name))
            elif field.name == "websafeKey":
                setattr(cf, field.name, conf.key.urlsafe())
        if displayName:
            setattr(cf, 'organizerDisplayName', displayName)
        cf.check_initialized()
        return cf


    def _createConferenceObject(self, request):
        """Create or update Conference object, returning ConferenceForm/request."""
        # preload necessary data items
        user = endpoints.get_current_user()
        if not user:
            raise endpoints.UnauthorizedException('Authorization required')
        user_id = getUserId(user)

        if not request.name:
            raise endpoints.BadRequestException("Conference 'name' field required")

        # copy ConferenceForm/ProtoRPC Message into dict
        data = {field.name: getattr(request, field.name) for field in request.all_fields()}
        del data['websafeKey']
        del data['organizerDisplayName']

        # add default values for those missing (both data model & outbound Message)
        for df in DEFAULTS:
            if data[df] in (None, []):
                data[df] = DEFAULTS[df]
                setattr(request, df, DEFAULTS[df])

        # convert dates from strings to Date objects; set month based on start_date
        if data['startDate']:
            data['startDate'] = datetime.strptime(data['startDate'][:10], "%Y-%m-%d").date()
            data['month'] = data['startDate'].month
        else:
            data['month'] = 0
        if data['endDate']:
            data['endDate'] = datetime.strptime(data['endDate'][:10], "%Y-%m-%d").date()

        # set seatsAvailable to be same as maxAttendees on creation
        if data["maxAttendees"] > 0:
            data["seatsAvailable"] = data["maxAttendees"]
        # generate Profile Key based on user ID and Conference
        # ID based on Profile key get Conference key from ID
        p_key = ndb.Key(Profile, user_id)
        c_id = Conference.allocate_ids(size=1, parent=p_key)[0]
        c_key = ndb.Key(Conference, c_id, parent=p_key)
        data['key'] = c_key
        data['organizerUserId'] = request.organizerUserId = user_id

        # create Conference, send email to organizer confirming
        # creation of Conference & return (modified) ConferenceForm
        Conference(**data).put()
        taskqueue.add(params={'email': user.email(),
            'conferenceInfo': repr(request)},
            url='/tasks/send_confirmation_email'
        )
        return request


    @ndb.transactional()
    def _updateConferenceObject(self, request):
        user = endpoints.get_current_user()
        if not user:
            raise endpoints.UnauthorizedException('Authorization required')
        user_id = getUserId(user)

        # copy ConferenceForm/ProtoRPC Message into dict
        data = {field.name: getattr(request, field.name) for field in request.all_fields()}

        # update existing conference
        conf = ndb.Key(urlsafe=request.websafeConferenceKey).get()
        # check that conference exists
        if not conf:
            raise endpoints.NotFoundException(
                'No conference found with key: %s' % request.websafeConferenceKey)

        # check that user is owner
        if user_id != conf.organizerUserId:
            raise endpoints.ForbiddenException(
                'Only the owner can update the conference.')

        # Not getting all the fields, so don't create a new object; just
        # copy relevant fields from ConferenceForm to Conference object
        for field in request.all_fields():
            data = getattr(request, field.name)
            # only copy fields where we get data
            if data not in (None, []):
                # special handling for dates (convert string to Date)
                if field.name in ('startDate', 'endDate'):
                    data = datetime.strptime(data, "%Y-%m-%d").date()
                    if field.name == 'startDate':
                        conf.month = data.month
                # write to Conference object
                setattr(conf, field.name, data)
        conf.put()
        prof = ndb.Key(Profile, user_id).get()
        return self._copyConferenceToForm(conf, getattr(prof, 'displayName'))


    @endpoints.method(ConferenceForm, ConferenceForm, path='conference',
            http_method='POST', name='createConference')
    def createConference(self, request):
        """Create new conference."""
        return self._createConferenceObject(request)


    @endpoints.method(CONF_POST_REQUEST, ConferenceForm,
            path='conference/{websafeConferenceKey}',
            http_method='PUT', name='updateConference')
    def updateConference(self, request):
        """Update conference w/provided fields & return w/updated info."""
        return self._updateConferenceObject(request)


    @endpoints.method(CONF_GET_REQUEST, ConferenceForm,
            path='conference/{websafeConferenceKey}',
            http_method='GET', name='getConference')
    def getConference(self, request):
        """Return requested conference (by websafeConferenceKey)."""
        # get Conference object from request; bail if not found
        conf = ndb.Key(urlsafe=request.websafeConferenceKey).get()
        if not conf:
            raise endpoints.NotFoundException(
                'No conference found with key: %s' % request.websafeConferenceKey)
        prof = conf.key.parent().get()
        # return ConferenceForm
        return self._copyConferenceToForm(conf, getattr(prof, 'displayName'))


    @endpoints.method(message_types.VoidMessage, ConferenceForms,
            path='getConferencesCreated',
            http_method='POST', name='getConferencesCreated')
    def getConferencesCreated(self, request):
        """Return conferences created by user."""
        # make sure user is authed
        user = endpoints.get_current_user()
        if not user:
            raise endpoints.UnauthorizedException('Authorization required')
        user_id = getUserId(user)

        # create ancestor query for all key matches for this user
        confs = Conference.query(ancestor=ndb.Key(Profile, user_id))
        prof = ndb.Key(Profile, user_id).get()
        # return set of ConferenceForm objects per Conference
        return ConferenceForms(
            items=[self._copyConferenceToForm(conf, getattr(prof, 'displayName')) for conf in confs]
        )

    def _getGenericQuery(self, request, responseObj, callback, cls):
        """Maps async to the inputed callback the generic query result."""
        q = cls.query()  # Get the cls(ndb.Model) object
        inequality_filters, filters = self._formatGenericFilters(request.filters, cls)
        #Filter the query in the equality filters
        for filtr in filters:
            formatted_query = ndb.query.FilterNode(filtr["field"], filtr["operator"], filtr["value"])
            q = q.filter(formatted_query)
        #The inequality filters will be filtered in the callback function and added to the responseObj if it pass the filter
        return q.map_async(lambda ent: callback(ent, responseObj, inequality_filters))

    def _formatGenericFilters(self, filters, cls):
        """Parse, check validity and format user supplied filters, separated in regular_filters and inequality_filters."""
        regular_filters = []
        inequality_filters = []
        for f in filters:
            filtr = {field.name: getattr(f, field.name) for field in f.all_fields()}
            # Adjust the filter's operator and format it's value accordin to the field's proper format
            try:
                filtr["operator"] = OPERATORS[filtr["operator"]]
                filtr["value"] = cls.formatFilter(filtr["field"], filtr["value"])
            except KeyError:
                raise endpoints.BadRequestException("Filter contains invalid field or operator.")
            # Every operation except "=" is an inequality
            if filtr["operator"] != "=":
                inequality_filters.append(filtr)
            else:  # if it is an inequality, it will be appended on the inequality_filters
                regular_filters.append(filtr)
        return (inequality_filters, regular_filters)

    def _getQuery(self, request):
        """Return formatted query from the submitted filters."""
        q = Conference.query()
        inequality_filter, filters = self._formatFilters(request.filters)

        # If exists, sort on inequality filter first
        if not inequality_filter:
            q = q.order(Conference.name)
        else:
            q = q.order(ndb.GenericProperty(inequality_filter))
            q = q.order(Conference.name)

        for filtr in filters:
            if filtr["field"] in ["month", "maxAttendees"]:
                filtr["value"] = int(filtr["value"])
            formatted_query = ndb.query.FilterNode(filtr["field"], filtr["operator"], filtr["value"])
            q = q.filter(formatted_query)
        return q


    def _formatFilters(self, filters):
        """Parse, check validity and format user supplied filters."""
        formatted_filters = []
        inequality_field = None

        for f in filters:
            filtr = {field.name: getattr(f, field.name) for field in f.all_fields()}

            try:
                filtr["field"] = FIELDS[filtr["field"]]
                filtr["operator"] = OPERATORS[filtr["operator"]]
            except KeyError:
                raise endpoints.BadRequestException("Filter contains invalid field or operator.")

            # Every operation except "=" is an inequality
            if filtr["operator"] != "=":
                # check if inequality operation has been used in previous filters
                # disallow the filter if inequality was performed on a different field before
                # track the field on which the inequality operation is performed
                if inequality_field and inequality_field != filtr["field"]:
                    raise endpoints.BadRequestException("Inequality filter is allowed on only one field.")
                else:
                    inequality_field = filtr["field"]

            formatted_filters.append(filtr)
        return (inequality_field, formatted_filters)


    @endpoints.method(ConferenceQueryForms, ConferenceForms,
            path='queryConferences',
            http_method='POST',
            name='queryConferences')
    def queryConferences(self, request):
        """Query for conferences."""
        conferences = self._getQuery(request)

        # need to fetch organiser displayName from profiles
        # get all keys and use get_multi for speed
        organisers = [(ndb.Key(Profile, conf.organizerUserId)) for conf in conferences]
        profiles = ndb.get_multi(organisers)

        # put display names in a dict for easier fetching
        names = {}
        for profile in profiles:
            names[profile.key.id()] = profile.displayName

        # return individual ConferenceForm object per Conference
        return ConferenceForms(
                items=[self._copyConferenceToForm(conf, names[conf.organizerUserId]) for conf in \
                conferences]
        )


# - - - Session objects - - - - - - - - - - - - - - - - -

    def _copySessionToForm(self, sess):
        """Copy relevant fields from Session to SessionForm."""
        sf = SessionForm()
        for field in sf.all_fields():
            if hasattr(sess, field.name):
                # convert Date to date string; just copy others
                if field.name in ['date','duration','start']:
                    setattr(sf, field.name, str(getattr(sess, field.name)))
                else:
                    setattr(sf, field.name, getattr(sess, field.name))
            elif field.name == "websafeKey":
                setattr(sf, field.name, sess.key.urlsafe())

        sf.check_initialized()
        return sf


    def _createSessionObject(self, request):
        """Create or update Session object, returning SessionForm/request."""
        # preload necessary data items
        user = endpoints.get_current_user()
        if not user:
            raise endpoints.UnauthorizedException('Authorization required')
        user_id = getUserId(user)

        if not request.name:
            raise endpoints.BadRequestException("Session 'name' field required")

        # copy SessionForm/ProtoRPC Message into dict
        data = {field.name: getattr(request, field.name) for field in request.all_fields()}
        del data['websafeKey']
        del data['websafeConferenceKey']

        # convert dates/times from strings to Date/Time objects;
        if data['duration']:
            data['duration'] = datetime.strptime(data['duration'][:5], "%H:%M").time()
        if data['date']:
            data['date'] = datetime.strptime(data['date'][:10], "%Y-%m-%d").date()
        if data['start']:
            data['start'] = datetime.strptime(data['start'][:5], "%H:%M").time()

        # generate Profile Key based on user ID and Session
        # ID based on Profile key get Session key from ID
        c_key = ndb.Key(urlsafe=request.websafeConferenceKey)
        s_id = Session.allocate_ids(size=1, parent=c_key)[0]
        s_key = ndb.Key(Session, s_id, parent=c_key)
        data['key'] = s_key

        # creation of Session & return (modified) SessionForm
        Session(**data).put()

        return self._copySessionToForm(request)

    @endpoints.method(CONF_GET_REQUEST, SessionForms,
            path='getConferenceSessions',
            http_method='GET', name='getConferenceSessions')
    def getConferenceSessions(self, request):
        """Return all sessions related to a conference (by websafeConferenceKey)."""
        # get the Conference key from the urlSafe key
        confKey = ndb.Key(urlsafe=request.websafeConferenceKey)
        if not confKey:
            raise endpoints.NotFoundException(
                'No conference found with key: %s' % request.websafeConferenceKey)
        # Query the sessions that have this conference as a parent
        sessions = Session.query(ancestor=confKey).fetch()
        # return SessionForms
        return SessionForms(
                items=[self._copySessionToForm(sess) for sess in \
                sessions]
        )

    @endpoints.method(SPEAKER_GET_BY_NAME_REQUEST, SessionForms,
            path='getSessionsBySpeaker',
            http_method='GET', name='getSessionsBySpeaker')
    def getSessionsBySpeaker(self, request):
        """Return all sessions related to a speaker (by speaker name)."""
        # check if the speaker is defined in the request
        if not request.speaker:
            raise endpoints.BadRequestException(
                'The "speaker" field is required, inputed value: %s' % request.speaker)
        # Query the sessions that have this speaker
        sessions = Session.query(Session.speaker == request.speaker).fetch()
        # return SessionForms
        return SessionForms(
                items=[self._copySessionToForm(sess) for sess in \
                sessions]
        )

    @endpoints.method(SESSION_GET_BY_TYPE_REQUEST, SessionForms,
            path='getConferenceSessionsByType',
            http_method='GET', name='getConferenceSessionsByType')
    def getConferenceSessionsByType(self, request):
        """Return all sessions related to a speaker (by speaker name)."""
        # check if the all the necessary fields are defined in the request
        if not request.websafeConferenceKey:
            raise endpoints.BadRequestException(
                'The "websafeConferenceKey" field is required, inputed value: %s' % request.websafeConferenceKey)
        elif not request.typeOfSession:
            raise endpoints.BadRequestException(
                'The "typeOfSession" field is required, inputed value: %s' % request.typeOfSession)
        # get the Conference key from the urlSafe key
        confKey = ndb.Key(urlsafe=request.websafeConferenceKey)
        if not confKey:
            raise endpoints.NotFoundException(
                'No conference found with key: %s' % request.websafeConferenceKey)
        # Query the sessions that have this speaker
        sessions = Session.query(Session.typeOfSession == request.typeOfSession, ancestor=confKey).fetch()
        # return SessionForms
        return SessionForms(
                items=[self._copySessionToForm(sess) for sess in \
                sessions]
        )

    @endpoints.method(SESSION_GET_BY_COMPANY_REQUEST, SessionForms,
            path='getConferenceSessionsByCompany',
            http_method='GET', name='getConferenceSessionsByCompany')
    def getConferenceSessionsByCompany(self, request):
        """Return all sessions that have speakers that works for the inputed company."""
        # check if the all the necessary fields are defined in the request
        if not request.websafeConferenceKey:
            raise endpoints.BadRequestException(
                'The "websafeConferenceKey" field is required, inputed value: %s' % request.websafeConferenceKey)
        elif not request.company:
            raise endpoints.BadRequestException(
                'The "company" field is required, inputed value: %s' % request.company)
        # get the Conference key from the urlSafe key
        confKey = ndb.Key(urlsafe=request.websafeConferenceKey)
        if not confKey:
            raise endpoints.NotFoundException(
                'No conference found with key: %s' % request.websafeConferenceKey)
        # Query the sessions that have this speaker
        sessions = Session.query(ancestor=confKey).fetch()
        speakers = self._getSpeakerBycompany(request.company)
        filtr = []
        for sess in sessions:
            for sp in sess.speaker:
                if sp in speakers:
                    filtr.append(sess)
        # return SessionForms
        return SessionForms(
                items=[self._copySessionToForm(sess) for sess in \
                filtr]
        )

    @endpoints.method(SESSION_GET_BY_SPECIALTY_REQUEST, SessionForms,
            path='getConferenceSessionsBySpeakerSpecialty',
            http_method='GET', name='getConferenceSessionsBySpeakerSpecialty')
    def getConferenceSessionsBySpeakerSpecialty(self, request):
        """Return all sessions that have speakers with the desired specialty."""
        # check if the all the necessary fields are defined in the request
        if not request.websafeConferenceKey:
            raise endpoints.BadRequestException(
                'The "websafeConferenceKey" field is required, inputed value: %s' % request.websafeConferenceKey)
        elif not request.specialty:
            raise endpoints.BadRequestException(
                'The "specialty" field is required, inputed value: %s' % request.specialty)
        # get the Conference key from the urlSafe key
        confKey = ndb.Key(urlsafe=request.websafeConferenceKey)
        if not confKey:
            raise endpoints.NotFoundException(
                'No conference found with key: %s' % request.websafeConferenceKey)
        # Query the sessions that have this speaker
        sessions = Session.query(ancestor=confKey).fetch()
        speakers = self._getSpeakerByspecialty(request.specialty)
        filtr = []
        for sess in sessions:
            for sp in sess.speaker:
                if sp in speakers:
                    filtr.append(sess)
        # return SessionForms
        return SessionForms(
                items=[self._copySessionToForm(sess) for sess in \
                filtr]
        )

    @endpoints.method(SESSION_POST_REQUEST, SessionForm, path='session',
            http_method='POST', name='createSession')
    #@ndb.transactional(xg=True) speacker don't have an ancestor so I cant make this a transactional method
    def createSession(self, request):
        """Create new session."""
        #Get the current user
        user = endpoints.get_current_user()
        if not user:
            raise endpoints.UnauthorizedException('Authorization required')
        user_id = getUserId(user)
        #Check if the current user is the organizer of this conference
        conf = ndb.Key(urlsafe=request.websafeConferenceKey).get()
        if user_id != conf.organizerUserId:
            raise endpoints.UnauthorizedException('Only the organizer is allowed to create sessions for this conference. You: '+str(user_id)+'; Organizer: '+str(conf.organizerUserId))
        # Check if is a speaker with this name on de DB
        speakers = request.speaker
        for speaker in speakers:
            if not self._getSpeakerByName(speaker):
                # If the speaker is not registered, it will be created as a default speaker
                self._createSpeakerByName(speaker)
            # Add a task to the queue to check if this speaker should be the featured speaker for this conference
            taskqueue.add(params={'speaker': speaker,
                'conferenceKey': request.websafeConferenceKey},
                url='/tasks/update_featured_speaker'
            )
        # Create a session
        return self._createSessionObject(request)

    @endpoints.method(SESSION_KEY, ProfileForm, path='addSessionToWishlist',
            http_method='POST', name='addSessionToWishlist')
    def addSessionToWishlist(self, request):
        """Add or remove(if the session is already in the list) a session to a user Wishlist."""
        swsk = request.websafeSessionKey
        prof = self._getProfileFromUser()  # get user Profile
        #check if the session is in
        if swsk in prof.sessionWishlist:
            prof.sessionWishlist.remove(swsk)
        else:
            prof.sessionWishlist.append(swsk)
        #save the profile and return it's form
        prof.put()
        return self._copyProfileToForm(prof)

    @endpoints.method(message_types.VoidMessage, SessionForms, path='getSessionsInWishlist',
            http_method='POST', name='getSessionsInWishlist')
    def getSessionsInWishlist(self, request):
        """Return all the sessions in the user Wishlist."""
        prof = self._getProfileFromUser()  # get user Profile
        kList = []
        for sess in prof.sessionWishlist:
            try:
                kList.append(ndb.Key(urlsafe=str(sess)))
            except Exception, e:
                logging.error('Erro getSessionsInWishlist, erro: '+str(e)+'; Key: '+str(sess))
        sessions = ndb.get_multi(kList)
        # return SessionForms
        return SessionForms(
            items=[self._copySessionToForm(s) for s in sessions]
        )

    @endpoints.method(SESSION_KEY, SessionForm, path='getSessionByKey',
            http_method='POST', name='getSessionByKey')
    def getSessionByKey(self, request):
        '''Return the session based on the informed key'''
        return self._copySessionToForm(ndb.Key(urlsafe=request.websafeSessionKey).get())

    @endpoints.method(QueryForms, SessionForms,
            path='querySessions',
            http_method='POST', name='querySessions')
    def querySessions(self, request):
        """Return all sessions based on the inputed parameters, no limit of inequality filters."""
        # Set the items list, it will recieve all the entities that passed the callback
        items = []
        # Must call the get_result on the future object to ensure all the entities will be retrived
        i = self._getGenericQuery(request, items, self._callbackQuerySessions, Session).get_result()
        return SessionForms(items=items)

    def _callbackQuerySessions(self, entity, responseObj, inequality_filters):
        """Recieve every entity retrived in the generic query, check if it passes the inequality filters,
        and if it does, transform it in a SessionForm and append it to the responseObj."""
        #Check if the session pass in the inequality filters
        if validadeInequalityFilter(inequality_filters, entity):
            # Append in the response object the form version of the session
            responseObj.append(self._copySessionToForm(entity))

    #MONTAR querySpeaker P PROVAR QUE DA P USAR A _getGenericQuery p todas as tabelas

# - - - Speaker objects - - - - - - - - - - - - - - - - -
    def _updateFeaturedSpeaker(self, speaker, conferenceKey):
        """Update the featured speaker in Memcache."""
        featuredMsg = ''
        # get the Conference key from the urlSafe key
        confKey = ndb.Key(urlsafe=conferenceKey)
        # Query the number sessions in this conference that have this speaker
        qSessions = Session.query(Session.speaker == speaker, ancestor=confKey)
        if qSessions.count() > 1:  # Check if the speaker apears on more than one session
            # Update the featured speaker on the conference
            conference = confKey.get()
            if conference.featuredSpeaker != speaker:
                conference.featuredSpeaker = speaker
                conference.put()
            # Generate a featured mesage to cache
            featured = "The featured speaker is "+str(speaker)+', and the sessions are: '
            s = ', '.join(s.name for s in qSessions.fetch())
            featuredMsg = featured+s
            memcache.set(MEMCACHE_FEATURED_SPEAKER_PRE_KEY+conferenceKey, featuredMsg)

        return featuredMsg

    def _createSpeakerByName(self, name):
        """Creates a default speaker with the inputed name."""
        data = DEFAULT_SPEAKER
        data['name'] = name
        return Speaker(**data).put()

    def _getSpeakerByName(self, name):
        """Return the speaker (as a SpeakerForm) with the inputed name."""
        speaker = Speaker.query(Speaker.name == name).get()
        return self._copySpeakerToForm(speaker) if speaker else False

    def _getSpeakerBycompany(self, company):
        """Return the speakers (as a list of speaker's names) from the inputed company."""
        speakers = Speaker.query(Speaker.company == company).fetch()
        return [speaker.name for speaker in speakers]

    def _getSpeakerByspecialty(self, specialty):
        """Return the speakers (as a list of speaker's names) from the inputed specialty."""
        speakers = Speaker.query(Speaker.specialty == specialty).fetch()
        return [speaker.name for speaker in speakers]

    def _copySpeakerToForm(self, spea):
        """Copy relevant fields from Speaker to SpeakerForm."""
        sf = SpeakerForm()
        for field in sf.all_fields():
            if hasattr(spea, field.name):
                setattr(sf, field.name, getattr(spea, field.name))
            elif field.name == "websafeKey":
                setattr(sf, field.name, spea.key.urlsafe())

        sf.check_initialized()
        return sf


    def _createSpeakerObject(self, request):
        """Create or update Speaker object, returning SpeakerForm/request."""
        # preload necessary data items
        user = endpoints.get_current_user()
        if not user:
            raise endpoints.UnauthorizedException('Authorization required')
        user_id = getUserId(user)

        if not request.name:
            raise endpoints.BadRequestException("Speaker 'name' field required")

        # copy SpeakerForm/ProtoRPC Message into dict
        data = {field.name: getattr(request, field.name) for field in request.all_fields()}
        del data['websafeKey']

        # generate Profile Key based on user ID and Speaker
        # ID based on Profile key get Speaker key from ID
        s_id = Speaker.allocate_ids(size=1)[0]
        s_key = ndb.Key(Speaker, s_id)
        data['key'] = s_key

        # creation of Speaker & return (modified) SpeakerForm
        Speaker(**data).put()

        return self._copySpeakerToForm(request)

    @endpoints.method(QueryForms, SpeakerForms,
            path='querySpeaker',
            http_method='POST', name='querySpeaker')
    def querySpeaker(self, request):
        """Return all speakers based on the inputed parameters, no limit of inequality filters."""
        # Set the items list, it will recieve all the entities that passed the callback
        items = []
        # Must call the get_result on the future object to ensure all the entities will be retrived
        i = self._getGenericQuery(request, items, self._callbackQuerySpeakers, Speaker).get_result()
        return SpeakerForms(items=items)

    def _callbackQuerySpeakers(self, entity, responseObj, inequality_filters):
        """Recieve every entity retrived in the generic query, check if it passes the inequality filters,
        and if it does, transform it in a SpeakerForm and append it to the responseObj."""
        # Check if the speaker pass in the inequality filters
        if validadeInequalityFilter(inequality_filters, entity):
            # Append in the response object the form version of the speaker
            responseObj.append(self._copySpeakerToForm(entity))

    @endpoints.method(CONF_GET_REQUEST, StringMessage, path='getFeaturedSpeaker',
            http_method='POST', name='getFeaturedSpeaker')
    def getFeaturedSpeaker(self, request):
        """Return the conference's actual featured speaker."""
        msg = memcache.get(MEMCACHE_FEATURED_SPEAKER_PRE_KEY+request.websafeConferenceKey)
        if not msg or msg == '':
            conf = ndb.Key(urlsafe=request.websafeConferenceKey).get()
            msg = self._updateFeaturedSpeaker(conf.featuredSpeaker, request.websafeConferenceKey)
        return StringMessage(data=msg or "")

    @endpoints.method(SPEAKER_POST_REQUEST, SpeakerForm, path='speaker',
            http_method='POST', name='createSpeaker')
    def createSpeaker(self, request):
        """Create new Speaker."""
        # Create a Speaker
        return self._createSpeakerObject(request)


# - - - Profile objects - - - - - - - - - - - - - - - - - - -

    def _copyProfileToForm(self, prof):
        """Copy relevant fields from Profile to ProfileForm."""
        # copy relevant fields from Profile to ProfileForm
        pf = ProfileForm()
        for field in pf.all_fields():
            if hasattr(prof, field.name):
                # convert t-shirt string to Enum; just copy others
                if field.name == 'teeShirtSize':
                    setattr(pf, field.name, getattr(TeeShirtSize, getattr(prof, field.name)))
                else:
                    setattr(pf, field.name, getattr(prof, field.name))
        pf.check_initialized()
        return pf


    def _getProfileFromUser(self):
        """Return user Profile from datastore, creating new one if non-existent."""
        # make sure user is authed
        user = endpoints.get_current_user()
        if not user:
            raise endpoints.UnauthorizedException('Authorization required')

        # get Profile from datastore
        user_id = getUserId(user)
        p_key = ndb.Key(Profile, user_id)
        profile = p_key.get()
        # create new Profile if not there
        if not profile:
            profile = Profile(
                key = p_key,
                displayName = user.nickname(),
                mainEmail= user.email(),
                teeShirtSize = str(TeeShirtSize.NOT_SPECIFIED),
            )
            profile.put()

        return profile      # return Profile


    def _doProfile(self, save_request=None):
        """Get user Profile and return to user, possibly updating it first."""
        # get user Profile
        prof = self._getProfileFromUser()

        # if saveProfile(), process user-modifyable fields
        if save_request:
            for field in ('displayName', 'teeShirtSize'):
                if hasattr(save_request, field):
                    val = getattr(save_request, field)
                    if val:
                        setattr(prof, field, str(val))
                        #if field == 'teeShirtSize':
                        #    setattr(prof, field, str(val).upper())
                        #else:
                        #    setattr(prof, field, val)
                        prof.put()

        # return ProfileForm
        return self._copyProfileToForm(prof)


    @endpoints.method(message_types.VoidMessage, ProfileForm,
            path='profile', http_method='GET', name='getProfile')
    def getProfile(self, request):
        """Return user profile."""
        return self._doProfile()


    @endpoints.method(ProfileMiniForm, ProfileForm,
            path='profile', http_method='POST', name='saveProfile')
    def saveProfile(self, request):
        """Update & return user profile."""
        return self._doProfile(request)


# - - - Announcements - - - - - - - - - - - - - - - - - - - -

    @staticmethod
    def _cacheAnnouncement():
        """Create Announcement & assign to memcache; used by
        memcache cron job & putAnnouncement().
        """
        confs = Conference.query(ndb.AND(
            Conference.seatsAvailable <= 5,
            Conference.seatsAvailable > 0)
        ).fetch(projection=[Conference.name])

        if confs:
            # If there are almost sold out conferences,
            # format announcement and set it in memcache
            announcement = ANNOUNCEMENT_TPL % (
                ', '.join(conf.name for conf in confs))
            memcache.set(MEMCACHE_ANNOUNCEMENTS_KEY, announcement)
        else:
            # If there are no sold out conferences,
            # delete the memcache announcements entry
            announcement = ""
            memcache.delete(MEMCACHE_ANNOUNCEMENTS_KEY)

        return announcement


    @endpoints.method(message_types.VoidMessage, StringMessage,
            path='conference/announcement/get',
            http_method='GET', name='getAnnouncement')
    def getAnnouncement(self, request):
        """Return Announcement from memcache."""
        return StringMessage(data=memcache.get(MEMCACHE_ANNOUNCEMENTS_KEY) or "")


# - - - Registration - - - - - - - - - - - - - - - - - - - -

    @ndb.transactional(xg=True)
    def _conferenceRegistration(self, request, reg=True):
        """Register or unregister user for selected conference."""
        retval = None
        prof = self._getProfileFromUser() # get user Profile

        # check if conf exists given websafeConfKey
        # get conference; check that it exists
        wsck = request.websafeConferenceKey
        conf = ndb.Key(urlsafe=wsck).get()
        if not conf:
            raise endpoints.NotFoundException(
                'No conference found with key: %s' % wsck)

        # register
        if reg:
            # check if user already registered otherwise add
            if wsck in prof.conferenceKeysToAttend:
                raise ConflictException(
                    "You have already registered for this conference")

            # check if seats avail
            if conf.seatsAvailable <= 0:
                raise ConflictException(
                    "There are no seats available.")

            # register user, take away one seat
            prof.conferenceKeysToAttend.append(wsck)
            conf.seatsAvailable -= 1
            retval = True

        # unregister
        else:
            # check if user already registered
            if wsck in prof.conferenceKeysToAttend:

                # unregister user, add back one seat
                prof.conferenceKeysToAttend.remove(wsck)
                conf.seatsAvailable += 1
                retval = True
            else:
                retval = False

        # write things back to the datastore & return
        prof.put()
        conf.put()
        return BooleanMessage(data=retval)


    @endpoints.method(message_types.VoidMessage, ConferenceForms,
            path='conferences/attending',
            http_method='GET', name='getConferencesToAttend')
    def getConferencesToAttend(self, request):
        """Get list of conferences that user has registered for."""
        prof = self._getProfileFromUser() # get user Profile
        conf_keys = [ndb.Key(urlsafe=wsck) for wsck in prof.conferenceKeysToAttend]
        conferences = ndb.get_multi(conf_keys)

        # get organizers
        organisers = [ndb.Key(Profile, conf.organizerUserId) for conf in conferences]
        profiles = ndb.get_multi(organisers)

        # put display names in a dict for easier fetching
        names = {}
        for profile in profiles:
            names[profile.key.id()] = profile.displayName

        # return set of ConferenceForm objects per Conference
        return ConferenceForms(items=[self._copyConferenceToForm(conf, names[conf.organizerUserId])\
         for conf in conferences]
        )


    @endpoints.method(CONF_GET_REQUEST, BooleanMessage,
            path='conference/{websafeConferenceKey}',
            http_method='POST', name='registerForConference')
    def registerForConference(self, request):
        """Register user for selected conference."""
        return self._conferenceRegistration(request)


    @endpoints.method(CONF_GET_REQUEST, BooleanMessage,
            path='conference/{websafeConferenceKey}',
            http_method='DELETE', name='unregisterFromConference')
    def unregisterFromConference(self, request):
        """Unregister user for selected conference."""
        return self._conferenceRegistration(request, reg=False)


    @endpoints.method(message_types.VoidMessage, ConferenceForms,
            path='filterPlayground',
            http_method='GET', name='filterPlayground')
    def filterPlayground(self, request):
        """Filter Playground"""
        q = Conference.query()
        # field = "city"
        # operator = "="
        # value = "London"
        # f = ndb.query.FilterNode(field, operator, value)
        # q = q.filter(f)
        q = q.filter(Conference.city=="London")
        q = q.filter(Conference.topics=="Medical Innovations")
        q = q.filter(Conference.month==6)

        return ConferenceForms(
            items=[self._copyConferenceToForm(conf, "") for conf in q]
        )


api = endpoints.api_server([ConferenceApi]) # register API
