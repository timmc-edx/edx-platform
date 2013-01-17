import logging
from cStringIO import StringIO
from lxml import etree
from path import path  # NOTE (THK): Only used for detecting presence of syllabus
import requests
import time
from datetime import datetime

from xmodule.modulestore import Location
from xmodule.seq_module import SequenceDescriptor, SequenceModule
from xmodule.timeparse import parse_time, stringify_time
from xmodule.util.decorators import lazyproperty
from xmodule.graders import grader_from_conf
from datetime import datetime
import json
import logging
import requests
import time
import copy


log = logging.getLogger(__name__)


edx_xml_parser = etree.XMLParser(dtd_validation=False, load_dtd=False,
                                 remove_comments=True, remove_blank_text=True)

_cached_toc = {}


class CourseDescriptor(SequenceDescriptor):
    module_class = SequenceModule

    template_dir_name = 'course'

    class Textbook:
        def __init__(self, title, book_url):
            self.title = title
            self.book_url = book_url
            self.table_of_contents = self._get_toc_from_s3()
            self.start_page = int(self.table_of_contents[0].attrib['page'])

            # The last page should be the last element in the table of contents,
            # but it may be nested. So recurse all the way down the last element
            last_el = self.table_of_contents[-1]
            while last_el.getchildren():
                last_el = last_el[-1]

            self.end_page = int(last_el.attrib['page'])

        @property
        def table_of_contents(self):
            return self.table_of_contents

        def _get_toc_from_s3(self):
            """
            Accesses the textbook's table of contents (default name "toc.xml") at the URL self.book_url

            Returns XML tree representation of the table of contents
            """
            toc_url = self.book_url + 'toc.xml'

            # cdodge: I've added this caching of TOC because in Mongo-backed instances (but not Filesystem stores)
            # course modules have a very short lifespan and are constantly being created and torn down.
            # Since this module in the __init__() method does a synchronous call to AWS to get the TOC
            # this is causing a big performance problem. So let's be a bit smarter about this and cache
            # each fetch and store in-mem for 10 minutes.
            # NOTE: I have to get this onto sandbox ASAP as we're having runtime failures. I'd like to swing back and
            # rewrite to use the traditional Django in-memory cache.
            try:
                # see if we already fetched this
                if toc_url in _cached_toc:
                    (table_of_contents, timestamp) = _cached_toc[toc_url]
                    age = datetime.now() - timestamp
                    # expire every 10 minutes
                    if age.seconds < 600:
                        return table_of_contents
            except Exception as err:
                pass

            # Get the table of contents from S3
            log.info("Retrieving textbook table of contents from %s" % toc_url)
            try:
                r = requests.get(toc_url)
            except Exception as err:
                msg = 'Error %s: Unable to retrieve textbook table of contents at %s' % (err, toc_url)
                log.error(msg)
                raise Exception(msg)

            # TOC is XML. Parse it
            try:
                table_of_contents = etree.fromstring(r.text)
                _cached_toc[toc_url] = (table_of_contents, datetime.now())
            except Exception as err:
                msg = 'Error %s: Unable to parse XML for textbook table of contents at %s' % (err, toc_url)
                log.error(msg)
                raise Exception(msg)

            return table_of_contents

    def __init__(self, system, definition=None, **kwargs):
        super(CourseDescriptor, self).__init__(system, definition, **kwargs)
        self.textbooks = []
        for title, book_url in self.definition['data']['textbooks']:
            try:
                self.textbooks.append(self.Textbook(title, book_url))
            except:
                # If we can't get to S3 (e.g. on a train with no internet), don't break
                # the rest of the courseware.
                log.exception("Couldn't load textbook ({0}, {1})".format(title, book_url))
                continue

        self.wiki_slug = self.definition['data']['wiki_slug'] or self.location.course

        msg = None
        if self.start is None:
            msg = "Course loaded without a valid start date. id = %s" % self.id
            # hack it -- start in 1970
            self.metadata['start'] = stringify_time(time.gmtime(0))
            log.critical(msg)
            system.error_tracker(msg)

        # NOTE: relies on the modulestore to call set_grading_policy() right after
        # init.  (Modulestore is in charge of figuring out where to load the policy from)

        # NOTE (THK): This is a last-minute addition for Fall 2012 launch to dynamically
        #   disable the syllabus content for courses that do not provide a syllabus
        self.syllabus_present = self.system.resources_fs.exists(path('syllabus'))
        self.set_grading_policy(self.definition['data'].get('grading_policy', None))

        self.test_center_exams = []
        test_center_info = self.metadata.get('testcenter_info')
        if test_center_info is not None:
            for exam_name in test_center_info:
                try:
                    exam_info = test_center_info[exam_name]
                    self.test_center_exams.append(self.TestCenterExam(self.id, exam_name, exam_info))
                except Exception as err:
                    # If we can't parse the test center exam info, don't break
                    # the rest of the courseware.
                    msg = 'Error %s: Unable to load test-center exam info for exam "%s" of course "%s"' % (err, exam_name, self.id)
                    log.error(msg)
                    continue

    def defaut_grading_policy(self):
        """
        Return a dict which is a copy of the default grading policy
        """
        default = {"GRADER" : [
                {
                    "type" : "Homework",
                    "min_count" : 12,
                    "drop_count" : 2,
                    "short_label" : "HW",
                    "weight" : 0.15
                },
                {
                    "type" : "Lab",
                    "min_count" : 12,
                    "drop_count" : 2,
                    "weight" : 0.15
                },
                {
                    "type" : "Midterm Exam",
                    "short_label" : "Midterm",
                    "min_count" : 1,
                    "drop_count" : 0,
                    "weight" : 0.3
                },
                {
                    "type" : "Final Exam",
                    "short_label" : "Final",
                    "min_count" : 1,
                    "drop_count" : 0,
                    "weight" : 0.4
                }
            ],
            "GRADE_CUTOFFS" : {
                "Pass" : 0.5
            }}
        return copy.deepcopy(default)

    def set_grading_policy(self, course_policy):
        """
        The JSON object can have the keys GRADER and GRADE_CUTOFFS. If either is
        missing, it reverts to the default.
        """
        if course_policy is None:
            course_policy = {}

        # Load the global settings as a dictionary
        grading_policy = self.defaut_grading_policy()

        # Override any global settings with the course settings
        grading_policy.update(course_policy)

        # Here is where we should parse any configurations, so that we can fail early
        grading_policy['RAW_GRADER'] = grading_policy['GRADER']  # used for cms access
        grading_policy['GRADER'] = grader_from_conf(grading_policy['GRADER'])
        self._grading_policy = grading_policy



    @classmethod
    def read_grading_policy(cls, paths, system):
        """Load a grading policy from the specified paths, in order, if it exists."""
        # Default to a blank policy dict
        policy_str = '{}'

        for policy_path in paths:
            if not system.resources_fs.exists(policy_path):
                continue
            log.debug("Loading grading policy from {0}".format(policy_path))
            try:
                with system.resources_fs.open(policy_path) as grading_policy_file:
                    policy_str = grading_policy_file.read()
                    # if we successfully read the file, stop looking at backups
                    break
            except (IOError):
                msg = "Unable to load course settings file from '{0}'".format(policy_path)
                log.warning(msg)

        return policy_str

    
    @classmethod
    def from_xml(cls, xml_data, system, org=None, course=None):
        instance = super(CourseDescriptor, cls).from_xml(xml_data, system, org, course)

        # bleh, have to parse the XML here to just pull out the url_name attribute
        # I don't think it's stored anywhere in the instance.
        course_file = StringIO(xml_data.encode('ascii','ignore'))
        xml_obj = etree.parse(course_file,parser=edx_xml_parser).getroot()

        policy_dir = None
        url_name = xml_obj.get('url_name', xml_obj.get('slug'))
        if url_name:
            policy_dir = 'policies/' + url_name

        # Try to load grading policy
        paths = ['grading_policy.json']
        if policy_dir:
            paths = [policy_dir + '/grading_policy.json'] + paths

        try:
            policy = json.loads(cls.read_grading_policy(paths, system))
        except ValueError:
            system.error_tracker("Unable to decode grading policy as json")
            policy = None
        
        # cdodge: import the grading policy information that is on disk and put into the
        # descriptor 'definition' bucket as a dictionary so that it is persisted in the DB
        instance.definition['data']['grading_policy'] = policy

        # now set the current instance. set_grading_policy() will apply some inheritance rules
        instance.set_grading_policy(policy)

        return instance


    @classmethod
    def definition_from_xml(cls, xml_object, system):
        textbooks = []
        for textbook in xml_object.findall("textbook"):
            textbooks.append((textbook.get('title'), textbook.get('book_url')))
            xml_object.remove(textbook)

        #Load the wiki tag if it exists
        wiki_slug = None
        wiki_tag = xml_object.find("wiki")
        if wiki_tag is not None:
            wiki_slug = wiki_tag.attrib.get("slug", default=None)
            xml_object.remove(wiki_tag)

        definition = super(CourseDescriptor, cls).definition_from_xml(xml_object, system)

        definition.setdefault('data', {})['textbooks'] = textbooks
        definition['data']['wiki_slug'] = wiki_slug

        return definition

    def has_ended(self):
        """
        Returns True if the current time is after the specified course end date.
        Returns False if there is no end date specified.
        """
        if self.end is None:
            return False

        return time.gmtime() > self.end

    def has_started(self):
        return time.gmtime() > self.start

    @property
    def end(self):
        return self._try_parse_time("end")
    @end.setter
    def end(self, value):
        if isinstance(value, time.struct_time):
            self.metadata['end'] = stringify_time(value)
    @property
    def enrollment_start(self):
        return self._try_parse_time("enrollment_start")
        
    @enrollment_start.setter
    def enrollment_start(self, value):
        if isinstance(value, time.struct_time):
            self.metadata['enrollment_start'] = stringify_time(value)
    @property
    def enrollment_end(self):        
        return self._try_parse_time("enrollment_end")
        
    @enrollment_end.setter
    def enrollment_end(self, value):
        if isinstance(value, time.struct_time):
            self.metadata['enrollment_end'] = stringify_time(value)
        
    @property
    def grader(self):
        return self._grading_policy['GRADER']
    
    @property
    def raw_grader(self):
        return self._grading_policy['RAW_GRADER']
    
    @raw_grader.setter
    def raw_grader(self, value):
        # NOTE WELL: this change will not update the processed graders. If we need that, this needs to call grader_from_conf
        self._grading_policy['RAW_GRADER'] = value
        self.definition['data'].setdefault('grading_policy',{})['GRADER'] = value

    @property
    def grade_cutoffs(self):
        return self._grading_policy['GRADE_CUTOFFS']
    
    @grade_cutoffs.setter
    def grade_cutoffs(self, value):
        self._grading_policy['GRADE_CUTOFFS'] = value
        self.definition['data'].setdefault('grading_policy',{})['GRADE_CUTOFFS'] = value
    

    @property
    def lowest_passing_grade(self):
        return min(self._grading_policy['GRADE_CUTOFFS'].values())

    @property
    def tabs(self):
        """
        Return the tabs config, as a python object, or None if not specified.
        """
        return self.metadata.get('tabs')

    @tabs.setter
    def tabs(self, value):
        self.metadata['tabs'] = value

    @property
    def show_calculator(self):
        return self.metadata.get("show_calculator", None) == "Yes"

    @property
    def is_new(self):
        # The course is "new" if either if the metadata flag is_new is
        # true or if the course has not started yet
        flag = self.metadata.get('is_new', None)
        if flag is None:
            return self.days_until_start > 1
        elif isinstance(flag, basestring):
            return flag.lower() in ['true', 'yes', 'y']
        else:
            return bool(flag)

    @property
    def days_until_start(self):
        def convert_to_datetime(timestamp):
            return datetime.fromtimestamp(time.mktime(timestamp))

        start_date = convert_to_datetime(self.start)

        #  Try to use course advertised date if we can parse it
        advertised_start = self.metadata.get('advertised_start', None)
        if advertised_start:
            try:
                start_date = datetime.strptime(advertised_start,
                                               "%Y-%m-%dT%H:%M")
            except ValueError:
                pass  # Invalid date, keep using 'start''

        now = convert_to_datetime(time.gmtime())
        days_until_start = (start_date - now).days
        return days_until_start

    @lazyproperty
    def grading_context(self):
        """
        This returns a dictionary with keys necessary for quickly grading
        a student. They are used by grades.grade()

        The grading context has two keys:
        graded_sections - This contains the sections that are graded, as
            well as all possible children modules that can affect the
            grading. This allows some sections to be skipped if the student
            hasn't seen any part of it.

            The format is a dictionary keyed by section-type. The values are
            arrays of dictionaries containing
                "section_descriptor" : The section descriptor
                "xmoduledescriptors" : An array of xmoduledescriptors that
                    could possibly be in the section, for any student

        all_descriptors - This contains a list of all xmodules that can
            effect grading a student. This is used to efficiently fetch
            all the xmodule state for a StudentModuleCache without walking
            the descriptor tree again.


        """

        all_descriptors = []
        graded_sections = {}

        def yield_descriptor_descendents(module_descriptor):
            for child in module_descriptor.get_children():
                yield child
                for module_descriptor in yield_descriptor_descendents(child):
                    yield module_descriptor

        for c in self.get_children():
            sections = []
            for s in c.get_children():
                if s.metadata.get('graded', False):
                    xmoduledescriptors = list(yield_descriptor_descendents(s))
                    xmoduledescriptors.append(s)

                    # The xmoduledescriptors included here are only the ones that have scores.
                    section_description = { 'section_descriptor' : s, 'xmoduledescriptors' : filter(lambda child: child.has_score, xmoduledescriptors) }

                    section_format = s.metadata.get('format', "")
                    graded_sections[ section_format ] = graded_sections.get( section_format, [] ) + [section_description]

                    all_descriptors.extend(xmoduledescriptors)
                    all_descriptors.append(s)

        return { 'graded_sections' : graded_sections,
                 'all_descriptors' : all_descriptors,}


    @staticmethod
    def make_id(org, course, url_name):
        return '/'.join([org, course, url_name])

    @staticmethod
    def id_to_location(course_id):
        '''Convert the given course_id (org/course/name) to a location object.
        Throws ValueError if course_id is of the wrong format.
        '''
        org, course, name = course_id.split('/')
        return Location('i4x', org, course, 'course', name)

    @staticmethod
    def location_to_id(location):
        '''Convert a location of a course to a course_id.  If location category
        is not "course", raise a ValueError.

        location: something that can be passed to Location
        '''
        loc = Location(location)
        if loc.category != "course":
            raise ValueError("{0} is not a course location".format(loc))
        return "/".join([loc.org, loc.course, loc.name])

    @property
    def id(self):
        """Return the course_id for this course"""
        return self.location_to_id(self.location)

    @property
    def start_date_text(self):
        parsed_advertised_start = self._try_parse_time('advertised_start')

        # If the advertised start isn't a real date string, we assume it's free
        # form text...
        if parsed_advertised_start is None and \
           ('advertised_start' in self.metadata):
            return self.metadata['advertised_start']

        displayed_start = parsed_advertised_start or self.start

        # If we have neither an advertised start or a real start, just return TBD
        if not displayed_start:
            return "TBD"

        return time.strftime("%b %d, %Y", displayed_start)

    @property
    def end_date_text(self):
        return time.strftime("%b %d, %Y", self.end)

    # An extra property is used rather than the wiki_slug/number because
    # there are courses that change the number for different runs. This allows
    # courses to share the same css_class across runs even if they have
    # different numbers.
    #
    # TODO get rid of this as soon as possible or potentially build in a robust
    # way to add in course-specific styling. There needs to be a discussion
    # about the right way to do this, but arjun will address this ASAP. Also
    # note that the courseware template needs to change when this is removed.
    @property
    def css_class(self):
        return self.metadata.get('css_class', '')

    @property
    def info_sidebar_name(self):
        return self.metadata.get('info_sidebar_name', 'Course Handouts')

    @property
    def discussion_link(self):
        """TODO: This is a quick kludge to allow CS50 (and other courses) to
        specify their own discussion forums as external links by specifying a
        "discussion_link" in their policy JSON file. This should later get
        folded in with Syllabus, Course Info, and additional Custom tabs in a
        more sensible framework later."""
        return self.metadata.get('discussion_link', None)

    @property
    def forum_posts_allowed(self):
        try:
            blackout_periods = [(parse_time(start), parse_time(end))
                                for start, end
                                in self.metadata.get('discussion_blackouts', [])]
            now = time.gmtime()
            for start, end in blackout_periods:
                if start <= now <= end:
                    return False
        except:
            log.exception("Error parsing discussion_blackouts for course {0}".format(self.id))

        return True

    @property
    def hide_progress_tab(self):
        """TODO: same as above, intended to let internal CS50 hide the progress tab
        until we get grade integration set up."""
        # Explicit comparison to True because we always want to return a bool.
        return self.metadata.get('hide_progress_tab') == True

    @property
    def end_of_course_survey_url(self):
        """
        Pull from policy.  Once we have our own survey module set up, can change this to point to an automatically
        created survey for each class.

        Returns None if no url specified.
        """
        return self.metadata.get('end_of_course_survey_url')

    class TestCenterExam(object):
        def __init__(self, course_id, exam_name, exam_info):
            self.course_id = course_id
            self.exam_name = exam_name
            self.exam_info = exam_info
            self.exam_series_code = exam_info.get('Exam_Series_Code') or exam_name
            self.display_name = exam_info.get('Exam_Display_Name') or self.exam_series_code
            self.first_eligible_appointment_date = self._try_parse_time('First_Eligible_Appointment_Date')
            if self.first_eligible_appointment_date is None:
                raise ValueError("First appointment date must be specified")
            # TODO: If defaulting the last appointment date, it should be the 
            # *end* of the same day, not the same time.  It's going to be used as the
            # end of the exam overall, so we don't want the exam to disappear too soon.  
            # It's also used optionally as the registration end date, so time matters there too.
            self.last_eligible_appointment_date = self._try_parse_time('Last_Eligible_Appointment_Date') # or self.first_eligible_appointment_date
            if self.last_eligible_appointment_date is None:
                raise ValueError("Last appointment date must be specified")
            self.registration_start_date = self._try_parse_time('Registration_Start_Date') or time.gmtime(0)
            self.registration_end_date = self._try_parse_time('Registration_End_Date') or self.last_eligible_appointment_date
            # do validation within the exam info:
            if self.registration_start_date > self.registration_end_date:
                raise ValueError("Registration start date must be before registration end date")
            if self.first_eligible_appointment_date > self.last_eligible_appointment_date:
                raise ValueError("First appointment date must be before last appointment date")
            if self.registration_end_date > self.last_eligible_appointment_date:
                raise ValueError("Registration end date must be before last appointment date")
            

        def _try_parse_time(self, key):
            """
            Parse an optional metadata key containing a time: if present, complain
            if it doesn't parse.
            Return None if not present or invalid.
            """
            if key in self.exam_info:
                try:
                    return parse_time(self.exam_info[key])
                except ValueError as e:
                    msg = "Exam {0} in course {1} loaded with a bad exam_info key '{2}': '{3}'".format(self.exam_name, self.course_id, self.exam_info[key], e)
                    log.warning(msg)
                return None

        def has_started(self):
            return time.gmtime() > self.first_eligible_appointment_date

        def has_ended(self):
            return time.gmtime() > self.last_eligible_appointment_date

        def has_started_registration(self):
            return time.gmtime() > self.registration_start_date

        def has_ended_registration(self):
            return time.gmtime() > self.registration_end_date

        def is_registering(self):
            now = time.gmtime()
            return now >= self.registration_start_date and now <= self.registration_end_date
            
        @property
        def first_eligible_appointment_date_text(self):
            return time.strftime("%b %d, %Y", self.first_eligible_appointment_date)

        @property
        def last_eligible_appointment_date_text(self):
            return time.strftime("%b %d, %Y", self.last_eligible_appointment_date)

        @property
        def registration_end_date_text(self):
            return time.strftime("%b %d, %Y", self.registration_end_date)

    @property
    def current_test_center_exam(self):
        exams = [exam for exam in self.test_center_exams if exam.has_started_registration() and not exam.has_ended()]
        if len(exams) > 1:
            # TODO: output some kind of warning.  This should already be 
            # caught if we decide to do validation at load time.
            return exams[0]
        elif len(exams) == 1:
            return exams[0]
        else:
            return None

    @property
    def title(self):
        return self.display_name

    @property
    def number(self):
        return self.location.course

    @property
    def org(self):
        return self.location.org

