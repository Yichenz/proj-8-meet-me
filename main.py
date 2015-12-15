import flask
from flask import render_template
from flask import request
from flask import url_for
import uuid

import json
import logging

# Date handling 
import arrow # Replacement for datetime, based on moment.js
import datetime # But we still need time
from dateutil import tz  # For interpreting local times

# OAuth2  - Google library implementation for convenience
from oauth2client import client
import httplib2   # used in oauth2 flow

# Google API for services 
from apiclient import discovery

# handles the mongoDB operations
import db_helper

#for db keys
import bson
from bson.objectid import ObjectId

###
# Globals
###
import CONFIG
app = flask.Flask(__name__)

SCOPES = 'https://www.googleapis.com/auth/calendar.readonly'
CLIENT_SECRET_FILE = CONFIG.GOOGLE_LICENSE_KEY
APPLICATION_NAME = 'Project 8: MeetMe'


#############################
#
#  Pages (routed from URLs)
#
#############################


@app.route("/")
@app.route("/index")
def index():
    app.logger.debug("Entering index")
    
    #initialize defaults
    init_session_values()
    flask.session["processed_update"] = "no"
    flask.session["confirmed"] = "no"
    
    return render_template('index.html')

@app.route("/choose")
def choose(key = None):
    app.logger.debug("Entering choose")
    
    #initialize defaults
    flask.session["processed_delete"] = "no"
    flask.session['key_not_found'] = "false"
    
    #get key from the url
    key = request.args.get("key")
    flask.session['key'] = key
    
    #put the access links in the session
    flask.session["choose_url"] = flask.url_for("choose", key = key, _external = True)
    flask.session["participate_url"] = flask.url_for("participate", key = key, _external = True)
    
    #look up some info from the db
    try:
        entry = db_helper.find_by_id(ObjectId(key))
    except bson.errors.InvalidId:
        entry = None
    
    if entry is None:
        flask.session['key_not_found'] = "true"
    else:
        flask.session['free_times'] = entry["free_times"]
        flask.session['confirmed'] = entry["confirmed"]
    
    return render_template('choose.html')

@app.route("/participate")
def participate(key = None):
    app.logger.debug("Entering participate")

    #initialize defaults
    init_session_values()
    flask.session['key_not_found'] = "false"
    
    #get key from the url
    key = request.args.get("key")
    flask.session['key'] = key
    
    #look up some info from the db
    try:
        entry = db_helper.find_by_id(ObjectId(key))
    except bson.errors.InvalidId:
        entry = None
    
    if entry is None:
        flask.session['key_not_found'] = "true"
    else:
        flask.session['free_times'] = entry["free_times"]
        flask.session['daterange'] = entry["bounds"]["daterange"]
        flask.session['confirmed'] = entry["confirmed"]
    
    return render_template('participate.html')


####
#
#  Google calendar authorization:
#      Returns to the appropriate set_range function after inserting
#      the calendar_service object in the session state.  May
#      redirect to OAuth server first, and may take multiple
#      trips through the oauth2 callback function.
#
#  Protocol for use ON EACH REQUEST: 
#     First, check for valid credentials
#     If we don't have valid credentials
#         Get credentials (jump to the oauth2 protocol)
#         (redirects back to the calling function, this time with credentials)
#     If we do have valid credentials
#         Get the service object
#
#  The final result of successful authorization is a 'service'
#  object.  We use a 'service' object to actually retrieve data
#  from the Google services. Service objects are NOT serializable ---
#  we can't stash one in a cookie.  Instead, on each request we
#  get a fresh serivce object from our credentials, which are
#  serializable. 
#
#  Note that after authorization we always redirect to the calling function.
#  If this is unsatisfactory, we'll need a session variable to use
#  as a 'continuation' or 'return address' to use instead. 
#
####


def valid_credentials():
    """
    Returns OAuth2 credentials if we have valid
    credentials in the session.  This is a 'truthy' value.
    Return None if we don't have credentials, or if they
    have expired or are otherwise invalid.  This is a 'falsy' value. 
    """
    if 'credentials' not in flask.session:
      return None

    credentials = client.OAuth2Credentials.from_json(
        flask.session['credentials'])

    if (credentials.invalid or
        credentials.access_token_expired):
      return None
    return credentials


def get_gcal_service(credentials):
    """
    We need a Google calendar 'service' object to obtain
    list of calendars, busy times, etc.  This requires
    authorization. If authorization is already in effect,
    we'll just return with the authorization. Otherwise,
    control flow will be interrupted by authorization, and we'll
    end up redirected back to the first calling function *without a service object*.
    Then the second call will succeed without additional authorization.
    """
    app.logger.debug("Entering get_gcal_service")
    http_auth = credentials.authorize(httplib2.Http())
    service = discovery.build('calendar', 'v3', http=http_auth)
    app.logger.debug("Returning service")
    return service


@app.route('/oauth2callback_index')
def oauth2callback_index():
    """
    The 'flow' has this one place to call back to.  We'll enter here
    more than once as steps in the flow are completed, and need to keep
    track of how far we've gotten. The first time we'll do the first
    step, the second time we'll skip the first step and do the second,
    and so on.
    """
    app.logger.debug("Entering oauth2callback_index")
    flow =  client.flow_from_clientsecrets(
        CLIENT_SECRET_FILE,
        scope= SCOPES,
        redirect_uri=flask.url_for('oauth2callback_index', _external=True))
  
    app.logger.debug("Got flow")
    if 'code' not in flask.request.args:
        app.logger.debug("Code not in flask.request.args")
        auth_uri = flow.step1_get_authorize_url()
        return flask.redirect(auth_uri)
        ## This will redirect back here, but the second time through
        ## we'll have the 'code' parameter set
    else:
        ## It's the second time through ... we can tell because
        ## we got the 'code' argument in the URL.
        app.logger.debug("Code was in flask.request.args")
        auth_code = flask.request.args.get('code')
        credentials = flow.step2_exchange(auth_code)
        flask.session['credentials'] = credentials.to_json()
        app.logger.debug("Got credentials")
        return flask.redirect(flask.url_for('setrange_from_index'))
    
    
@app.route('/oauth2callback_participate')
def oauth2callback_participate():
    """
    This function operates the same as oauth2callback_index, but is called
    from participate.
    """
    app.logger.debug("Entering oauth2callback_participate")
    flow =  client.flow_from_clientsecrets(
        CLIENT_SECRET_FILE,
        scope= SCOPES,
        redirect_uri=flask.url_for('oauth2callback_participate', _external=True))

    app.logger.debug("Got flow")
    if 'code' not in flask.request.args:
        app.logger.debug("Code not in flask.request.args")
        auth_uri = flow.step1_get_authorize_url()
        return flask.redirect(auth_uri)
        ## This will redirect back here, but the second time through
        ## we'll have the 'code' parameter set
    else:
        ## It's the second time through ... we can tell because
        ## we got the 'code' argument in the URL.
        app.logger.debug("Code was in flask.request.args")
        auth_code = flask.request.args.get('code')
        credentials = flow.step2_exchange(auth_code)
        flask.session['credentials'] = credentials.to_json()
        app.logger.debug("Got credentials")
        return flask.redirect(flask.url_for('setrange_from_participate'))


#####
#
#  Setrange functions: these process form input data and redirect
#
#####


@app.route('/setrange_from_index', methods=['GET', 'POST'])
def setrange_from_index():
    """
    Processes the form on the index page. Redirects to choose.
    
    NOTE: We pass through this function twice on the form submission, because of
          the google credential request. This is the reason that we have to
          check whether the form data is present, and save bounds in the session.
          
    NOTE: The begin dates/times have already been initialized with default
          values, and stored in the session, when the index page loads.
    """
    
    #user submitted data on the date range picker
    #(with optional time range input)
    daterange = request.form.get('daterange')
    if daterange is not None:
        daterange_parts = daterange.split()
        
        #set begin and end dates based on user input
        flask.session['begin_date'] = interpret_date(daterange_parts[0])
        flask.session['end_date'] = interpret_date(daterange_parts[2])
        
        #set begin and end times based on user input (if present)
        if( request.form.get('begin_time') != "" or request.form.get('end_time') != ""):
            flask.session['begin_time'] = interpret_time(request.form.get('begin_time'))
            flask.session['end_time'] = interpret_time(request.form.get('end_time'))
            if( flask.session['begin_time'] is None or
                    flask.session['begin_time'] is None or
                    flask.session['begin_time'] >= flask.session['end_time'] ):
                flask.session['bad_time'] = "true"
                return flask.redirect(flask.url_for("index"))
            flask.session['bad_time'] = "false"
        
        #set begin and end dateTimes based on user input
        begin_dateTime = arrow.get(flask.session['begin_date'])
        begin_hour = arrow.get(flask.session['begin_time']).hour
        begin_dateTime = begin_dateTime.replace(hours = begin_hour)
        flask.session['begin_dateTime'] = begin_dateTime.isoformat()
        
        end_dateTime = arrow.get(flask.session['end_date'])
        end_hour = arrow.get(flask.session['end_time']).hour
        end_dateTime = end_dateTime.replace(hours = end_hour)
        flask.session['end_dateTime'] = end_dateTime.isoformat()
        
        #announce
        app.logger.debug("Setrange_index parsed {} - {}  dates as {} - {}".format(
        daterange_parts[0], daterange_parts[2], 
        flask.session['begin_dateTime'], flask.session['end_dateTime']))
        
        #dictionary with date/time bounds
        flask.session['bounds'] = {
                    "begin_dateTime" : flask.session["begin_dateTime"],
                    "end_dateTime" : flask.session["end_dateTime"],
                    "begin_date" : flask.session["begin_date"],
                    "end_date" : flask.session["end_date"],
                    "begin_time" : flask.session["begin_time"],
                    "end_time" : flask.session["end_time"],
                    "daterange" : daterange
                 }
    
    #get google calendar credentials
    app.logger.debug("Checking credentials for Google calendar access")
    credentials = valid_credentials()
    if not credentials:
        app.logger.debug("Redirecting to authorization")
        return flask.redirect(flask.url_for('oauth2callback_index'))
    gcal_service = get_gcal_service(credentials)
    app.logger.debug("Returned from get_gcal_service")

    #get the busy time data
    calendars = list_calendars(gcal_service, flask.session['bounds'])
    
    #calcualte the free times
    free_times = get_free_times(calendars, flask.session['bounds'])
    
    #store the free times and bounds in the database
    key = db_helper.save(free_times, flask.session['bounds'])
    
    return flask.redirect(flask.url_for("choose", key = key))


@app.route('/setrange_from_participate', methods=['GET', 'POST'])
def setrange_from_participate():
    """
    Processes the form on the participate page. Redirects to participate.
    
    NOTE: We pass through this function twice on the form submission, because of
          the google credential request. This is the reason that we have to
          check whether the form data is present, and save bounds in the session.
          
    NOTE: The begin dates/times have already been initialized with default
          values, and stored in the session, when the participate page loads.
    """

    daterange = request.form.get('daterange')
    if daterange is not None:
        daterange_parts = daterange.split()
        
        #set begin and end dates based on user input
        flask.session['begin_date'] = interpret_date(daterange_parts[0])
        flask.session['end_date'] = interpret_date(daterange_parts[2])
        
        #set begin and end times based on user input (if present)
        if( request.form.get('begin_time') != "" or request.form.get('end_time') != ""):
            flask.session['begin_time'] = interpret_time(request.form.get('begin_time'))
            flask.session['end_time'] = interpret_time(request.form.get('end_time'))
            if( flask.session['begin_time'] is None or
                    flask.session['begin_time'] is None or
                    flask.session['begin_time'] >= flask.session['end_time'] ):
                flask.session['bad_time'] = "true"
                return flask.redirect(flask.url_for("participate", key = flask.session["key"]))
            flask.session['bad_time'] = "false"
        
        #set begin and end dateTimes based on user input
        begin_dateTime = arrow.get(flask.session['begin_date'])
        begin_hour = arrow.get(flask.session['begin_time']).hour
        begin_dateTime = begin_dateTime.replace(hours = begin_hour)
        flask.session['begin_dateTime'] = begin_dateTime.isoformat()
        
        end_dateTime = arrow.get(flask.session['end_date'])
        end_hour = arrow.get(flask.session['end_time']).hour
        end_dateTime = end_dateTime.replace(hours = end_hour)
        flask.session['end_dateTime'] = end_dateTime.isoformat()
        
        #announce
        app.logger.debug("Setrange_participate parsed {} - {}  dates as {} - {}".format(
        daterange_parts[0], daterange_parts[2], 
        flask.session['begin_dateTime'], flask.session['end_dateTime']))
        
        #dictionary with date/time bounds
        flask.session["bounds"] = {
                    "begin_dateTime" : flask.session["begin_dateTime"],
                    "end_dateTime" : flask.session["end_dateTime"],
                    "begin_date" : flask.session["begin_date"],
                    "end_date" : flask.session["end_date"],
                    "begin_time" : flask.session["begin_time"],
                    "end_time" : flask.session["end_time"],
                    "daterange" : daterange
                 }
    
    
    #get google calendar credentials
    app.logger.debug("Checking credentials for Google calendar access")
    credentials = valid_credentials()
    if not credentials:
        app.logger.debug("Redirecting to authorization")
        return flask.redirect(flask.url_for('oauth2callback_participate'))
    gcal_service = get_gcal_service(credentials)
    app.logger.debug("Returned from get_gcal_service")

    #get the calendars with busy time data
    calendars = list_calendars(gcal_service, flask.session["bounds"])
    
    #calcualte the new free times (free_times already in session from participate)
    new_free_times = get_free_times(calendars, flask.session["bounds"], flask.session["free_times"])
    
    #update the free times in the database
    status = db_helper.update( ObjectId(flask.session["key"]), new_free_times )
    
    #set "update" attribute in session
    flask.session["processed_update"] = flask.session["key"]
    
    return flask.redirect(flask.url_for("participate", key = flask.session["key"]))


#####
#
#  Database utility routes: these functions perform database queries
#
#####


@app.route("/_delete_proposal", methods = ['POST'])
def delete_proposal():
    """
    Tries to remove a proposal from the database. Redirects to index.
    """
    app.logger.debug("Got a delete proposal request")
    
    key = request.form.get("key")
    
    db_helper.delete_by_id( ObjectId(key) )
    
    flask.session["processed_delete"] = "yes"
    
    return flask.redirect(flask.url_for("index"))


@app.route("/_confirm_proposal", methods = ['POST'])
def confirm_proposal():
    """
    Updates the db when a proposal is confirmed. Redirects to choose.
    """
    app.logger.debug("Got a confirm proposal request")
    
    key = request.form.get("key")
    confirm_begin = request.form.get("confirm_begin")
    confirm_end = request.form.get("confirm_end")
    
    status = db_helper.update_confirmed(ObjectId(key), confirm_begin, confirm_end)
    
    return flask.redirect( flask.url_for("choose", key = flask.session["key"]) )


####
#
#   Initialize session variables 
#
####


def init_session_values():
    """
    Start with some reasonable defaults for date and time ranges.
    Note this must be run in app context ... can't call from main. 
    """
    # Default date span = tomorrow to 1 week from now
    now = arrow.now('local')
    tomorrow = now.replace(days=+1)
    nextweek = now.replace(days=+7)
    flask.session["begin_date"] = tomorrow.floor('day').isoformat()
    flask.session["end_date"] = nextweek.ceil('day').isoformat()
    flask.session["daterange"] = "{} - {}".format(
        tomorrow.format("MM/DD/YYYY"),
        nextweek.format("MM/DD/YYYY"))
    
    # Default time span: the entire day
    flask.session["begin_time"] = interpret_time("00:00")
    flask.session["end_time"] = interpret_time("23:59")
    

####
#
#   Parse dates/times
#
####


def interpret_time( text ):
    """
    Read time in a human-compatible format and
    interpret as ISO format with local timezone.
    May throw exception if time can't be interpreted. In that
    case it will also flash a message explaining accepted formats.
    """
    app.logger.debug("Decoding time '{}'".format(text))
    time_formats = ["ha", "h a", "h:mma",  "h:mm a", "H:mm"]
    try: 
        as_arrow = arrow.get(text, time_formats).replace(tzinfo=tz.tzlocal())
        app.logger.debug("Succeeded interpreting time")
    except:
        app.logger.debug("Failed to interpret time")
        return None
    return as_arrow.isoformat()

def interpret_date( text ):
    """
    Convert text of date to ISO format used internally,
    with the local time zone.
    """
    try:
      as_arrow = arrow.get(text, "MM/DD/YYYY").replace(
          tzinfo=tz.tzlocal())
    except:
        flask.flash("Date '{}' didn't fit expected format 12/31/2001")
        raise
    return as_arrow.isoformat()

def next_day(isotext):
    """
    ISO date + 1 day (used in query to Google calendar)
    """
    as_arrow = arrow.get(isotext)
    return as_arrow.replace(days=+1).isoformat()


####
#
#  Functions (NOT pages) that return some information
#
####


def get_free_times(calendars, bounds, free_times = None):
    """
    Given a list of 'calendar' dicts (each of which contains, in particular,
    a list of busy time intervals) and a dict of date/time ranges in ISO
    format, calculates a list of free time intervals.
    
    If the optional key-word argument free_times is provided, intersects
    the free times from the calendars with the free_time list provided.
    
    Arguments: -calendars, a list of 'calendar' dicts (see the 'list_calendars
                function)
               -bounds, a dict of date/time ranges (see the 'choose' function)
               -free_times, optional, a list of free times that has already
                been constructed (e.g., with this function)
    
    Returns: a list of free time intervals in ISO format
    
    Effects: none
    """
    #list of free times to be returned
    res = free_times
    
    #unpack the argument dictionary into arrow objects
    begin_dateTime = arrow.get(bounds["begin_dateTime"])
    end_dateTime = arrow.get(bounds["end_dateTime"])
    begin_date = arrow.get(bounds["begin_date"])
    end_date = arrow.get(bounds["end_date"])
    begin_time = arrow.get(bounds["begin_time"])
    end_time = arrow.get(bounds["end_time"])
    
    #set up the initial free times based on date and time ranges
    if res is None:
        res = []
        for r in arrow.Arrow.range('day', begin_dateTime, end_dateTime):
            daily_start = r.replace(hour=begin_time.hour)
            daily_start = daily_start.replace(minute=begin_time.minute)
            daily_end = r.replace(hour=end_time.hour)
            daily_end = daily_end.replace(minute=end_time.minute)
            res.append( [daily_start, daily_end] )
    else:
        #change the datetime to arrow for comparison
        temp_add = []
        temp_remove = []
        for t in res:
            t[0] = arrow.get(t[0])
            t[1] = arrow.get(t[1])
            
            #if the free time interval is outside the updated date range
            if t[0] > end_dateTime or t[1] < begin_dateTime:
                temp_remove.append(t)
            
            #if the free time interval is entirely outside the updated time range
            elif t[0].time() > end_time.time() or t[1].time() < begin_time.time():
                temp_remove.append(t)
            
            #if the free time interval is partially outside the updated time range
            elif t[0].time() < begin_time.time() and t[1].time() < end_time.time():
                new_start = t[0].replace(hour=begin_time.hour, minute = begin_time.minute)
                temp_add.append( [new_start, t[1]] )
                temp_remove.append(t)
                
            elif t[0].time() > begin_time.time() and t[1].time() > end_time.time():
                new_end = t[1].replace(hour=end_time.hour, minute = end_time.minute)
                temp_add.append( [t[0], new_end] )
                temp_remove.append(t)
                
            elif t[0].time() < begin_time.time() and t[1].time() > end_time.time():
                new_start = t[0].replace(hour=begin_time.hour, minute = begin_time.minute)
                new_end = t[1].replace(hour=end_time.hour, minute = end_time.minute)
                temp_add.append( [new_start, new_end] )
                temp_remove.append(t)
        
        #update the free time result list
        for x in temp_remove:
            res.remove(x)
        res.extend(temp_add)
    
    #iterate through the conflicting events
    for cal in calendars:
        for event in cal["events"]:
            start = event["start"]
            if 'dateTime' in start:
                start_dt = arrow.get(start['dateTime'])
            elif 'date' in start:
                start_dt = arrow.get(start['date'], 'YYYY-MM-DD').replace(
                                                            tzinfo=tz.tzlocal())
            end = event["end"]
            if 'dateTime' in end:
                end_dt = arrow.get(end['dateTime'])
            elif 'date' in start:
                end_dt = arrow.get(end['date'], 'YYYY-MM-DD').replace(
                                                            tzinfo=tz.tzlocal())
            
            #calculate the effect of this event on the free times
            temp_add = []
            temp_remove = []
            for t in res:
                l_interval = t[0]
                r_interval = t[1]
                #case1: event doesn't intersect interval
                if(end_dt <= l_interval or start_dt >= r_interval):
                    continue
                
                #case2: event intersects interval on the left
                elif(start_dt <= l_interval and end_dt < r_interval):
                    temp_add.append([end_dt, r_interval])
                    temp_remove.append(t)
                
                #case3: event intersects interval on the right
                elif(l_interval < start_dt and r_interval <= end_dt):
                    temp_add.append([l_interval, start_dt])
                    temp_remove.append(t)
                
                #case4: event is contained within the interval
                elif(l_interval < start_dt and end_dt < r_interval):
                    temp_add.append([l_interval, start_dt])
                    temp_add.append([end_dt, r_interval])
                    temp_remove.append(t)
                
                #case5: event contains the interval
                else:
                    temp_remove.append(t)
            
            #update the free time result list
            for x in temp_remove:
                res.remove(x)
            res.extend(temp_add)
                
    #format the result for storage in the flask session object
    for t in res:
        t[0] = t[0].isoformat()
        t[1] = t[1].isoformat()
    
    return sorted(res)
    

def list_calendars(service, bounds):
    """
    Given a google 'service' object, and a dict of date/time boundaries,
    return a list of calendars.  Each calendar is represented by a dict, so that
    it can be stored in the session object and converted to
    json for cookies. The returned list is sorted to have
    the primary calendar first, and selected (that is, displayed in
    Google Calendars web app) calendars before unselected calendars.
    
    Arguments: -service, a google 'service' object
               -bounds, a dict of date/time ranges (see the 'choose' function)
               
    Returns: a list of 'calendar' dicts
    
    Effects: announces function call to the log
    """
    app.logger.debug("Entering list_calendars")  
    calendar_list = service.calendarList().list().execute()["items"]
    result = [ ]
    
    #the standard id pulled in from google contains characters that are not
    #allowed in an html id, so we set up a simple numeric id for this purpose
    numeric_id = 0
    
    #unpack the argument dictionary into arrow objects
    begin_dateTime = arrow.get(bounds["begin_dateTime"])
    end_dateTime = arrow.get(bounds["end_dateTime"])
    begin_date = arrow.get(bounds["begin_date"])
    end_date = arrow.get(bounds["end_date"])
    begin_time = arrow.get(bounds["begin_time"])
    end_time = arrow.get(bounds["end_time"])
    
    for cal in calendar_list:
        kind = cal["kind"]
        id = cal["id"]
        
        #find events that intersect the range
        events = service.events().list(calendarId=id).execute()
        cal_events = []
        for event in events['items']:
            if 'transparency' not in event:
                start_flag = False
                end_flag = False

                #check whether the event begins in the range
                if 'start' in event:
                    start = event['start']
                    if 'dateTime' in start:
                        dT = arrow.get(start['dateTime'])
                        if( dT < end_dateTime and dT.time() < end_time.time() ):
                            start_flag = True
                    elif 'date' in start:
                        d = arrow.get(start['date'], 'YYYY-MM-DD').replace(
                                                            tzinfo=tz.tzlocal())
                        if( d <= end_date ):
                            start_flag = True
                
                #check whether the event ends in the range
                if 'end' in event:
                    end = event['end']
                    if 'dateTime' in end:
                        dT = arrow.get(end['dateTime'])
                        if( begin_dateTime < dT and begin_time.time() < dT.time() ):
                            end_flag = True
                    elif 'date' in start:
                        d = arrow.get(end['date'], 'YYYY-MM-DD').replace(
                                                            tzinfo=tz.tzlocal())
                        if( begin_date <= d ):
                            end_flag = True
                
                if start_flag and end_flag:
                    cal_events.append(event)
        
        if "description" in cal: 
            desc = cal["description"]
        else:
            desc = "(no description)"
        summary = cal["summary"]
        # Optional binary attributes with False as default
        selected = ("selected" in cal) and cal["selected"]
        primary = ("primary" in cal) and cal["primary"]
        

        result.append(
          { "kind": kind,
            "id": id,
            "num_id": numeric_id,
            "summary": summary,
            "selected": selected,
            "primary": primary,
            "events" : cal_events
            })
            
        numeric_id += 1
    return sorted(result, key=cal_sort_key)


def cal_sort_key( cal ):
    """
    Sort key for the list of calendars:  primary calendar first,
    then other selected calendars, then unselected calendars.
    (" " sorts before "X", and tuples are compared piecewise)
    """
    if cal["selected"]:
       selected_key = " "
    else:
       selected_key = "X"
    if cal["primary"]:
       primary_key = " "
    else:
       primary_key = "X"
    return (primary_key, selected_key, cal["summary"])


#################
#
# Functions used within the templates
#
#################


@app.template_filter( 'fmtdate' )
def format_arrow_date( date ):
    try: 
        normal = arrow.get( date )
        return normal.format("ddd MM/DD/YYYY")
    except:
        return "(bad date)"

@app.template_filter( 'fmttime' )
def format_arrow_time( time ):
    try:
        normal = arrow.get( time )
        return normal.format("HH:mm")
    except:
        return "(bad time)"

@app.template_filter( 'fmtdatetime' )
def format_arrow_time( time ):
    try:
        normal = arrow.get( time )
        return normal.format("MM/DD/YYYY HH:mm")
    except:
        return "(bad time)"
    
#############


if __name__ == "__main__":
  # App is created above so that it will
  # exist whether this is 'main' or not
  # (e.g., if we are running in a CGI script)

  app.secret_key = str(uuid.uuid4())  
  app.debug=CONFIG.DEBUG
  app.logger.setLevel(logging.DEBUG)
  # We run on localhost only if debugging,
  # otherwise accessible to world
  if CONFIG.DEBUG:
    # Reachable only from the same computer
    app.run(port=CONFIG.PORT)
  else:
    # Reachable from anywhere 
    app.run(port=CONFIG.PORT,host="0.0.0.0")
    
