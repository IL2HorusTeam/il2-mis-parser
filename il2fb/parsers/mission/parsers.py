# -*- coding: utf-8 -*-
"""
This module provides a set of parsers which can be used to obtain information
about IL-2 FB missions. Every parser is a one-pass parser. They can be used to
parse a whole mission file or to parse a single given section as well.
"""
import datetime
import math
import six
import sys

from abc import ABCMeta, abstractmethod

from il2fb.commons import Skills, UnitTypes
from il2fb.commons.flight import Formations, RoutePointTypes
from il2fb.commons.organization import AirForces, Belligerents, Regiments
from il2fb.commons.targets import TargetTypes, TargetPriorities
from il2fb.commons.weather import Conditions, Gust, Turbulence

from .constants import (
    IS_STATIONARY_AIRCRAFT_RESTORABLE, NULL, WEAPONS_CONTINUATION_MARK,
    ROUTE_POINT_EXTRA_PARAMETERS_MARK, ROUTE_POINT_RADIO_SILENCE,
)
from .exceptions import MissionParsingError
from .structures import (
    Point2D, Point3D, GroundRoutePoint, Building, StaticCamera,
)


def to_bool(value):
    """
    Converts a string representation of a number into boolean.

    :param str value: a string representation of a number to convert

    :returns: `False` if `value` is equal to `'0'`, `True` otherwise
    :rtype: :class:`bool`

    **Examples:**

    .. code-block:: python

       >>> to_bool('0')
       False
       >>> to_bool('1')
       True
       >>> to_bool('-1')
       True
    """
    return value != '0'


to_belligerent = lambda value: Belligerents.get_by_value(int(value))
to_skill = lambda value: Skills.get_by_value(int(value))
to_unit_type = lambda value: UnitTypes.get_by_value(value.lower())


class SectionParser(object):
    """
    Abstract base parser of a single section in a mission file.

    A common approach to parse a section can be described in the following way:

    #. Pass a section name (e.g. 'MAIN') to :meth:`start` method. If parser can
       process a section with such name, it will return `True` and then you can
       proceed.
    #. Pass section lines one-by-one to :meth:`parse_line`.
    #. When you are done, get your parsed data by calling :meth:`stop`. This
       will tell the parser that no more data will be given and the parsing can
       be finished.

    |
    **Example**:

    .. code-block:: python

       section_name = "Test section"
       lines = ["foo", "bar", "baz", "qux", ]
       parser = SomeParser()

       if parser.start(section_name):
           for line in lines:
              parser.parse_line(line)
           result = parser.stop()

    """

    __metaclass__ = ABCMeta

    #: Tells whether a parser was started.
    running = False

    #: An internal buffer which can be redefined.
    data = None

    def start(self, section_name):
        """
        Try to start a parser. If a section with given name can be parsed, the
        parser will initialize it's internal data structures and set
        :attr:`running` to `True`.

        :param str section_name: a name of section which is going to be parsed

        :returns: `True` if section with a given name can be parsed by parser,
                  `False` otherwise
        :rtype: :class:`bool`
        """
        result = self.check_section_name(section_name)
        if result:
            self.running = True
            self.init_parser(section_name)
        return result

    @abstractmethod
    def check_section_name(self, section_name):
        """
        Check whether a section with a given name can be parsed.

        :param str section_name: a name of section which is going to be parsed

        :returns: `True` if section with a given name can be parsed by parser,
                  `False` otherwise
        :rtype: :class:`bool`
        """

    @abstractmethod
    def init_parser(self, section_name):
        """
        Abstract method which is called by :meth:`start` to initialize
        internal data structures.

        :param str section_name: a name of section which is going to be parsed

        :returns: ``None``
        """

    @abstractmethod
    def parse_line(self, line):
        """
        Abstract method which is called manually to parse a line from mission
        section.

        :param str line: a single line to parse

        :returns: ``None``
        """

    def stop(self):
        """
        Stops parser and returns fully processed data.

        :returns: a data structure returned by :meth:`process_data` method

        :raises RuntimeError: if parser was not started
        """
        if not self.running:
            raise RuntimeError("Cannot stop parser which is not running")

        self.running = False
        return self.process_data()

    def process_data(self):
        """
        Returns fully parsed data. Is called by :meth:`stop` method.

        :returns: a data structure which is specific for every subclass
        """
        return self.data


class ValuesParser(SectionParser):
    """
    This is a base class for parsers which assume that a section, which is
    going to be parsed, consists of key-value pairs with unique keys, one pair
    per line.

    **Section definition example**::

       [some section name]
       key1 value1
       key2 value2
       key3 value3
    """

    def init_parser(self, section_name):
        """
        Implements abstract method. See :meth:`SectionParser.init_parser` for
        semantics.

        Initializes a dictionary to store raw keys and their values.
        """
        self.data = {}

    def parse_line(self, line):
        """
        Implements abstract method. See :meth:`SectionParser.parse_line` for
        semantics.

        Splits line into key-value pair and puts it into internal dictionary.
        """
        key, value = line.strip().split()
        self.data.update({key: value})


class CollectingParser(SectionParser):
    """
    This is a base class for parsers which assume that a section, which is
    going to be parsed, consists of homogeneous lines which describe different
    objects with one set of attributes.

    **Section definition example**::

       [some section name]
       object1_attr1 object1_attr2 object1_attr3 object1_attr4
       object2_attr1 object2_attr2 object2_attr3 object2_attr4
       object3_attr1 object3_attr2 object3_attr3 object3_attr4
    """

    def init_parser(self, section_name):
        """
        Implements abstract method. See :meth:`SectionParser.init_parser` for
        semantics.

        Initializes a list for storing collection of objects.
        """
        self.data = []

    def parse_line(self, line):
        """
        Implements abstract method. See :meth:`SectionParser.parse_line` for
        semantics.

        Just puts entire line to internal buffer. You probably will want to
        redefine this method to do some extra job on each line.
        """
        self.data.append(line.strip())


class MainParser(ValuesParser):
    """
    Parses ``MAIN`` section.
    View :ref:`detailed description <main-section>`.
    """

    def check_section_name(self, section_name):
        """
        Implements abstract method. See
        :meth:`SectionParser.check_section_name` for semantics.
        """
        return section_name == "MAIN"

    def process_data(self):
        """
        Redefines base method. See :meth:`SectionParser.process_data` for
        semantics.
        """
        weather_conditions = int(self.data['CloudType'])
        return {
            'location_loader': self.data['MAP'],
            'time': {
                'value': self._to_time(self.data['TIME']),
                'is_fixed': 'TIMECONSTANT' in self.data,
            },
            'weather_conditions': Conditions.get_by_value(weather_conditions),
            'cloud_base': int(float(self.data['CloudHeight'])),
            'player': {
                'belligerent': to_belligerent(self.data['army']),
                'flight_id': self.data.get('player'),
                'aircraft_index': int(self.data['playerNum']),
                'fixed_weapons': 'WEAPONSCONSTANT' in self.data,
            },
        }

    def _to_time(self, value):
        time = float(self.data['TIME'])
        minutes, hours = math.modf(time)
        return datetime.time(int(hours), int(minutes * 60))


class SeasonParser(ValuesParser):
    """
    Parses ``SEASON`` section.
    View :ref:`detailed description <season-section>`.
    """

    def check_section_name(self, section_name):
        """
        Implements abstract method. See
        :meth:`SectionParser.check_section_name` for semantics.
        """
        return section_name == "SEASON"

    def process_data(self):
        """
        Redefines base method. See :meth:`SectionParser.process_data` for
        semantics.

        Combines day, time and year into :class:`datetime.date` object.
        """
        date = datetime.date(int(self.data['Year']),
                             int(self.data['Month']),
                             int(self.data['Day']))
        return {'date': date, }


class WeatherParser(ValuesParser):
    """
    Parses ``WEATHER`` section.
    View :ref:`detailed description <weather-section>`.
    """

    def check_section_name(self, section_name):
        """
        Implements abstract method. See
        :meth:`SectionParser.check_section_name` for semantics.
        """
        return section_name == "WEATHER"

    def process_data(self):
        """
        Redefines base method. See :meth:`SectionParser.process_data` for
        semantics.
        """
        gust = int(self.data['Gust'])
        turbulence = int(self.data['Turbulence'])
        return {
            'weather': {
                'wind': {
                    'direction': float(self.data['WindDirection']),
                    'speed': float(self.data['WindSpeed']),
                },
                'gust': Gust.get_by_value(gust),
                'turbulence': Turbulence.get_by_value(turbulence),
            },
        }


class MDSParser(ValuesParser):
    """
    Parses ``MDS`` section.
    View :ref:`detailed description <mds-section>`.
    """

    def check_section_name(self, section_name):
        return section_name == "MDS"

    def parse_line(self, line):
        super(MDSParser, self).parse_line(line.replace('MDS_', ''))

    def process_data(self):
        return {
            'conditions': {
                'radar': {
                    'advanced_mode': to_bool(self.data['Radar_SetRadarToAdvanceMode']),
                    'refresh_interval': int(self.data['Radar_RefreshInterval']),
                    'ships': {
                        'big': {
                            'max_range': int(self.data['Radar_ShipRadar_MaxRange']),
                            'min_height': int(self.data['Radar_ShipRadar_MinHeight']),
                            'max_height': int(self.data['Radar_ShipRadar_MaxHeight']),
                        },
                        'small': {
                            'max_range': int(self.data['Radar_ShipSmallRadar_MaxRange']),
                            'min_height': int(self.data['Radar_ShipSmallRadar_MinHeight']),
                            'max_height': int(self.data['Radar_ShipSmallRadar_MaxHeight']),
                        },
                    },
                    'scouts': {
                        'max_range': int(self.data['Radar_ScoutRadar_MaxRange']),
                        'max_height': int(self.data['Radar_ScoutRadar_DeltaHeight']),
                        'alpha': int(self.data['Radar_ScoutGroundObjects_Alpha']),
                    },
                },
                'scouting': {
                    'ships_affect_radar': to_bool(self.data['Radar_ShipsAsRadar']),
                    'scouts_affect_radar': to_bool(self.data['Radar_ScoutsAsRadar']),
                    'only_scouts_complete_targets': to_bool(self.data['Radar_ScoutCompleteRecon']),
                },
                'communication': {
                    'tower_communication': to_bool(self.data['Radar_EnableTowerCommunications']),
                    'vectoring': not to_bool(self.data['Radar_DisableVectoring']),
                    'ai_radio_silence': to_bool(self.data['Misc_DisableAIRadioChatter']),
                },
                'home_bases': {
                    'hide_ai_aircrafts_after_landing': to_bool(self.data['Misc_DespawnAIPlanesAfterLanding']),
                    'hide_unpopulated': to_bool(self.data['Radar_HideUnpopulatedAirstripsFromMinimap']),
                    'hide_players_count': to_bool(self.data['Misc_HidePlayersCountOnHomeBase']),
                },
                'crater_visibility_muptipliers': {
                    'le_100kg': float(self.data['Misc_BombsCat1_CratersVisibilityMultiplier']),
                    'le_1000kg': float(self.data['Misc_BombsCat2_CratersVisibilityMultiplier']),
                    'gt_1000kg': float(self.data['Misc_BombsCat3_CratersVisibilityMultiplier']),
                },
            },
        }


class MDSScoutsParser(CollectingParser):
    """
    Parses ``MDS_Scouts`` section.
    View :ref:`detailed description <mds-scouts-section>`.
    """
    input_prefix = "MDS_Scouts_"
    output_prefix = "scouts_"

    def check_section_name(self, section_name):
        if not section_name.startswith(self.input_prefix):
            return False
        belligerent_name = self._get_belligerent_name(section_name)
        return bool(belligerent_name)

    def init_parser(self, section_name):
        super(MDSScoutsParser, self).init_parser(section_name)
        belligerent_name = self._get_belligerent_name(section_name)
        self.belligerent = Belligerents.get_by_name(belligerent_name)
        self.output_key = "{}{}".format(self.output_prefix, belligerent_name)

    def _get_belligerent_name(self, section_name):
        return section_name[len(self.input_prefix):].lower()

    def process_data(self):
        return {
            self.output_key: {
                'belligerent': self.belligerent,
                'aircrafts': self.data,
            },
        }


class RespawnTimeParser(ValuesParser):
    """
    Parses ``RespawnTime`` section.
    View :ref:`detailed description <respawn-time-section>`.
    """

    def check_section_name(self, section_name):
        return section_name == "RespawnTime"

    def process_data(self):
        return {
            'respawn_time': {
                'ships': {
                    'big': int(self.data['Bigship']),
                    'small': int(self.data['Ship']),
                },
                'balloons': int(self.data['Aeroanchored']),
                'artillery': int(self.data['Artillery']),
                'searchlights': int(self.data['Searchlight']),
            },
        }


class ChiefsParser(CollectingParser):
    """
    Parses ``Chiefs`` section.
    View :ref:`detailed description <chiefs-section>`.
    """

    def check_section_name(self, section_name):
        return section_name == "Chiefs"

    def parse_line(self, line):
        params = line.split()
        (uid, type_code, belligerent), params = params[0:3], params[3:]

        chief_type, code = type_code.split('.')
        try:
            chief_type = to_unit_type(chief_type)
        except:
            chief_type = None

        unit = {
            'id': uid,
            'code': code,
            'type': chief_type,
            'belligerent': to_belligerent(belligerent),
        }
        if params:
            hibernation, skill, recharge_time = params
            unit.update({
                'hibernation': int(hibernation),
                'skill': to_skill(skill),
                'recharge_time': float(recharge_time),
            })
        self.data.append(unit)

    def process_data(self):
        return {'moving_units': self.data, }


class ChiefRoadParser(CollectingParser):
    """
    Parses ``N_Chief_Road`` section.
    View :ref:`detailed description <chief-road-section>`.
    """
    id_suffix = "_Chief"
    section_suffix = "_Road"
    input_suffix = id_suffix + section_suffix
    output_prefix = 'route_'

    def check_section_name(self, section_name):
        if not section_name.endswith(self.input_suffix):
            return False
        unit_id = self._extract_unit_id(section_name)
        stop = unit_id.index(self.id_suffix)
        return unit_id[:stop].isdigit()

    def init_parser(self, section_name):
        super(ChiefRoadParser, self).init_parser(section_name)
        unit_id = self._extract_unit_id(section_name)
        self.output_key = "{}{}".format(self.output_prefix, unit_id)

    def _extract_unit_id(self, section_name):
        stop = section_name.index(self.section_suffix)
        return section_name[:stop]

    def parse_line(self, line):
        params = line.split()
        pos, params = params[0:2], params[3:]

        args = {
            'pos': Point2D(*pos),
        }
        is_checkpoint = bool(params)
        args['is_checkpoint'] = is_checkpoint
        if is_checkpoint:
            args['delay'] = int(params[0])
            args['section_length'] = int(params[1])
            args['speed'] = float(params[2])

        point = GroundRoutePoint(**args)
        self.data.append(point)

    def process_data(self):
        return {self.output_key: self.data}


class NStationaryParser(CollectingParser):
    """
    Parses ``NStationary`` section.
    View :ref:`detailed description <nstationary-section>`.
    """

    def init_parser(self, section_name):
        super(NStationaryParser, self).init_parser(section_name)
        self.subparsers = {
            'artillery': self._parse_artillery,
            'planes': self._parse_planes,
            'ships': self._parse_ships,
        }

    def check_section_name(self, section_name):
        return section_name == "NStationary"

    def parse_line(self, line):
        params = line.split()

        oid, object_name, belligerent = params[0], params[1], params[2]
        pos = params[3:5]
        rotation_angle = params[5]
        params = params[6:]

        type_name = self._get_type_name(object_name)
        try:
            object_type = to_unit_type(type_name)
        except:
            object_type = None

        static = ({
            'belligerent': to_belligerent(belligerent),
            'id': oid,
            'code': self._get_code(object_name),
            'pos': Point2D(*pos),
            'rotation_angle': float(rotation_angle),
            'type': object_type,
        })

        subparser = self.subparsers.get(type_name)
        if subparser:
            static.update(subparser(params))
        self.data.append(static)

    def _get_type_name(self, object_name):
        if object_name.startswith('ships'):
            return "ships"
        else:
            start = object_name.index('.') + 1
            stop = object_name.rindex('.')
            return object_name[start:stop]

    def _get_code(self, code):
        start = code.index('$') + 1
        return code[start:]

    def _parse_artillery(self, params):
        """
        Parse additional options for ``artillery`` type
        """
        awakening_time, the_range, skill, is_spotter = params
        return {
            'awakening_time': float(awakening_time),
            'range': int(the_range),
            'skill': to_skill(skill),
            'use_spotter': to_bool(is_spotter),
        }

    def _parse_planes(self, params):
        """
        Parse additional options for ``planes`` type
        """
        air_force, allows_spawning__restorable = params[1:3]
        skin, has_markings = params[4:]

        if air_force == NULL:
            air_force = AirForces.vvs_rkka
        else:
            try:
                air_force = AirForces.get_by_value(air_force)
            except ValueError:
                air_force = None

        is_restorable = allows_spawning__restorable == IS_STATIONARY_AIRCRAFT_RESTORABLE
        skin = None if skin == NULL else skin

        return {
            'air_force': air_force,
            'allows_spawning': to_bool(allows_spawning__restorable),
            'is_restorable': is_restorable,
            'skin': skin,
            'show_markings': to_bool(has_markings),
        }

    def _parse_ships(self, params):
        """
        Parse additional options for ``ships`` type
        """
        awakening_time, skill, recharge_time = params[1:]
        return {
            'awakening_time': float(awakening_time),
            'recharge_time': float(recharge_time),
            'skill': to_skill(skill),
        }

    def process_data(self):
        return {'stationary': self.data, }


class BuildingsParser(CollectingParser):
    """
    Parses ``Buildings`` section.
    View :ref:`detailed description <buildings-section>`.
    """

    def check_section_name(self, section_name):
        return section_name == "Buildings"

    def parse_line(self, line):
        params = line.split()
        oid, building_object, belligerent = params[:3]
        pos_x, pos_y, rotation_angle = params[3:]
        building_type, code = building_object.split('$')
        self.data.append(Building(
            id=oid,
            belligerent=to_belligerent(belligerent),
            code=code,
            pos=Point2D(pos_x, pos_y),
            rotation_angle=float(rotation_angle),
        ))

    def process_data(self):
        return {'buildings': self.data, }


class TargetParser(CollectingParser):
    """
    Parses ``Target`` section.
    View :ref:`detailed description <target-section>`.
    """

    def check_section_name(self, section_name):
        return section_name == "Target"

    def parse_line(self, line):
        params = line.split()

        type_code, priority, in_sleep_mode, delay = params[:4]
        params = params[4:]

        target_type = TargetTypes.get_by_value(int(type_code))
        target = {
            'type': target_type,
            'priority': TargetPriorities.get_by_value(int(priority)),
            'in_sleep_mode': to_bool(in_sleep_mode),
            'delay': int(delay),
        }

        subparser = TargetParser.subparsers.get(target_type)
        if subparser is not None:
            target.update(subparser(params))

        self.data.append(target)

    @staticmethod
    def to_destruction_level(value):
        return int(value) / 10

    def parse_destroy_or_cover_or_escort(params):
        """
        Parse extra parameters for targets with type 'destroy' or 'cover' or
        'escort'.
        """
        destruction_level = TargetParser.to_destruction_level(params[0])
        pos, waypoint, object_code = params[1:3], params[4], params[5]
        object_pos = params[6:8]
        return {
            'destruction_level': destruction_level,
            'pos': Point2D(*pos),
            'object': {
                'waypoint': int(waypoint),
                'id': object_code,
                'pos': Point2D(*object_pos),
            },
        }

    def parse_destroy_or_cover_bridge(params):
        """
        Parse extra parameters for targets with type 'destroy bridge' or
        'cover bridge'.
        """
        pos, object_code, object_pos = params[1:3], params[5], params[6:8]
        return {
            'pos': Point2D(*pos),
            'object': {
                'id': object_code,
                'pos': Point2D(*object_pos),
            },
        }

    def parse_destroy_or_cover_area(params):
        """
        Parse extra parameters for targets with type 'destroy area' or
        'cover area'.
        """
        destruction_level = TargetParser.to_destruction_level(params[0])
        pos_x, pos_y, radius = params[1:]
        return {
            'destruction_level': destruction_level,
            'pos': Point2D(pos_x, pos_y),
            'radius': int(radius),
        }

    def parse_recon(params):
        """
        Parse extra parameters for targets with 'recon' type.
        """
        requires_landing = params[0] != '500'
        pos, radius, params = params[1:3], params[3], params[4:]
        data = {
            'radius': int(radius),
            'requires_landing': requires_landing,
            'pos': Point2D(*pos),
        }
        if params:
            waypoint, object_code = params[:2]
            object_pos = params[2:]
            data['object'] = {
                'waypoint': int(waypoint),
                'id': object_code,
                'pos': Point2D(*object_pos),
            }
        return data

    subparsers = {
        TargetTypes.destroy: parse_destroy_or_cover_or_escort,
        TargetTypes.destroy_bridge: parse_destroy_or_cover_bridge,
        TargetTypes.destroy_area: parse_destroy_or_cover_area,
        TargetTypes.recon: parse_recon,
        TargetTypes.escort: parse_destroy_or_cover_or_escort,
        TargetTypes.cover: parse_destroy_or_cover_or_escort,
        TargetTypes.cover_area: parse_destroy_or_cover_area,
        TargetTypes.cover_bridge: parse_destroy_or_cover_bridge,
    }

    def process_data(self):
        return {'targets': self.data, }


class BornPlaceParser(CollectingParser):
    """
    Parses ``BornPlace`` section.
    View :ref:`detailed description <bornplace-section>`.
    """

    def check_section_name(self, section_name):
        return section_name == "BornPlace"

    def parse_line(self, line):
        (
            belligerent, the_range, pos_x, pos_y, has_parachutes,
            air_spawn_height, air_spawn_speed, air_spawn_heading, max_pilots,
            radar_min_height, radar_max_height, radar_range, air_spawn_always,
            enable_aircraft_limits, aircraft_limits_consider_lost,
            disable_spawning, friction_enabled, friction_value,
            aircraft_limits_consider_stationary, show_default_icon,
            air_spawn_if_deck_is_full, spawn_in_stationary,
            return_to_start_position
        ) = line.split()

        self.data.append({
            'range': int(the_range),
            'belligerent': to_belligerent(belligerent),
            'show_default_icon': to_bool(show_default_icon),
            'friction': {
                'enabled': to_bool(friction_enabled),
                'value': float(friction_value),
            },
            'spawning': {
                'enabled': not to_bool(disable_spawning),
                'with_parachutes': to_bool(has_parachutes),
                'max_pilots': int(max_pilots),
                'in_stationary': {
                    'enabled': to_bool(spawn_in_stationary),
                    'return_to_start_position': to_bool(return_to_start_position),
                },
                'in_air': {
                    'height': int(air_spawn_height),
                    'speed': int(air_spawn_speed),
                    'heading': int(air_spawn_heading),
                    'conditions': {
                        'always': to_bool(air_spawn_always),
                        'if_deck_is_full': to_bool(air_spawn_if_deck_is_full),
                    },
                },
            },
            'aircraft_limitations': {
                'enabled': to_bool(enable_aircraft_limits),
                'consider_lost': to_bool(aircraft_limits_consider_lost),
                'consider_stationary': to_bool(aircraft_limits_consider_stationary),
            },
            'radar': {
                'range': int(radar_range),
                'min_height': int(radar_min_height),
                'max_height': int(radar_max_height),
            },
            'pos': Point2D(pos_x, pos_y),
        })

    def process_data(self):
        return {'home_bases': self.data, }


class BornPlaceAircraftsParser(CollectingParser):
    """
    Parses ``BornPlaceN`` section.
    View :ref:`detailed description <bornplace-aircrafts-section>`.
    """
    input_prefix = 'BornPlace'
    output_prefix = 'home_base_aircrafts_'

    def check_section_name(self, section_name):
        if not section_name.startswith(self.input_prefix):
            return False
        try:
            self._extract_section_number(section_name)
        except ValueError:
            return False
        else:
            return True

    def init_parser(self, section_name):
        super(BornPlaceAircraftsParser, self).init_parser(section_name)
        self.output_key = (
            "{}{}".format(self.output_prefix,
                          self._extract_section_number(section_name)))
        self.aircraft = {}

    def _extract_section_number(self, section_name):
        start = len(self.input_prefix)
        return int(section_name[start:])

    def parse_line(self, line):
        chunks = line.split()

        if chunks[0] == WEAPONS_CONTINUATION_MARK:
            self.aircraft['weapon_limitations'].extend(chunks[1:])
        else:
            if self.aircraft:
                self.data.append(self.aircraft)
            (code, limit), allowed_weapons = chunks[:2], chunks[2:]
            self.aircraft = {
                'code': code,
                'limit': self._to_limit(limit),
                'weapon_limitations': allowed_weapons,
            }

    def _to_limit(self, value):
        return int(value) if int(value) >= 0 else None

    def process_data(self):
        if self.aircraft:
            aircraft, self.aircraft = self.aircraft, None
            self.data.append(aircraft)

        return {self.output_key: self.data, }


class BornPlaceAirForcesParser(CollectingParser):
    """
    Parses ``BornPlaceCountriesN`` section.
    View :ref:`detailed description <bornplace-air-forces-section>`.
    """
    input_prefix = 'BornPlaceCountries'
    output_prefix = 'home_base_air_forces_'

    def check_section_name(self, section_name):
        if not section_name.startswith(self.input_prefix):
            return False
        try:
            self._extract_section_number(section_name)
        except ValueError:
            return False
        else:
            return True

    def init_parser(self, section_name):
        super(BornPlaceAirForcesParser, self).init_parser(section_name)
        self.output_key = (
            "{}{}".format(self.output_prefix,
                          self._extract_section_number(section_name)))
        self.countries = {}

    def _extract_section_number(self, section_name):
        start = len(self.input_prefix)
        return int(section_name[start:])

    def parse_line(self, line):
        country = AirForces.get_by_value(line.strip())
        self.data.append(country)

    def process_data(self):
        return {self.output_key: self.data, }


class StaticCameraParser(CollectingParser):
    """
    Parses ``StaticCamera`` section.
    View :ref:`detailed description <static-camera-section>`.
    """

    def check_section_name(self, section_name):
        return section_name == "StaticCamera"

    def parse_line(self, line):
        pos_x, pos_y, pos_z, belligerent = line.split()
        self.data.append(StaticCamera(
            belligerent=to_belligerent(belligerent),
            pos=Point3D(pos_x, pos_y, pos_z),
        ))

    def process_data(self):
        return {'cameras': self.data, }


class FrontMarkerParser(CollectingParser):
    """
    Parses ``FrontMarker`` section.
    View :ref:`detailed description <front-marker-section>`.
    """

    def check_section_name(self, section_name):
        return section_name == "FrontMarker"

    def parse_line(self, line):
        oid, pos_x, pos_y, belligerent = line.split()
        self.data.append({
            'id': oid,
            'belligerent': to_belligerent(belligerent),
            'pos': Point2D(pos_x, pos_y),
        })

    def process_data(self):
        return {'markers': self.data, }


class RocketParser(CollectingParser):
    """
    Parses ``Rocket`` section.
    View :ref:`detailed description <rocket-section>`.
    """

    def check_section_name(self, section_name):
        return section_name == "Rocket"

    def parse_line(self, line):
        params = line.split()

        oid, code, belligerent = params[0:3]
        pos = params[3:5]
        rotation_angle, delay, count, period = params[5:9]
        destination = params[9:]

        self.data.append({
            'id': oid,
            'code': code,
            'belligerent': to_belligerent(belligerent),
            'pos': Point2D(*pos),
            'rotation_angle': float(rotation_angle),
            'delay': float(delay),
            'count': int(count),
            'period': float(period),
            'destination': Point2D(*destination) if destination else None
        })

    def process_data(self):
        return {'rockets': self.data}


class WingParser(CollectingParser):
    """
    Parses ``Wing`` section.
    View :ref:`detailed description <wing-section>`.
    """

    def check_section_name(self, section_name):
        return section_name == "Wing"

    def process_data(self):
        return {'flights': self.data}


class FlightInfoParser(ValuesParser):
    """
    Parses settings for a moving flight group.
    View :ref:`detailed description <flight-info-section>`.
    """

    def check_section_name(self, section_name):
        try:
            self._decompose_section_name(section_name)
        except:
            return False
        else:
            return True

    def init_parser(self, section_name):
        super(FlightInfoParser, self).init_parser(section_name)
        self.output_key = section_name
        self.flight_info = self._decompose_section_name(section_name)

    def _decompose_section_name(self, section_name):
        prefix = section_name[:-2]
        squadron, flight = section_name[-2:]

        try:
            regiment = None
            air_force = AirForces.get_by_flight_prefix(prefix)
        except ValueError:
            regiment = Regiments.get_by_code_name(prefix)
            air_force = regiment.air_force

        return {
            'id': section_name,
            'air_force': air_force,
            'regiment': regiment,
            'squadron_index': int(squadron),
            'flight_index': int(flight),
        }

    def process_data(self):
        count = int(self.data['Planes'])
        code = self.data['Class'].split('.', 1)[1]
        aircrafts = []

        def _add_if_present(target, key, value):
            if value:
                target[key] = value

        for i in range(count):
            aircraft = {
                'index': i,
                'has_markings': self._has_markings(i),
                'skill': self._get_skill(i),
            }
            _add_if_present(
                aircraft, 'aircraft_skin', self._get_skin('skin', i))
            _add_if_present(
                aircraft, 'nose_art', self._get_skin('nose_art', i))
            _add_if_present(
                aircraft, 'pilot_skin', self._get_skin('pilot', i))
            _add_if_present(
                aircraft, 'spawn_object', self._get_spawn_object_id(i))
            aircrafts.append(aircraft)

        self.flight_info.update({
            'ai_only': 'OnlyAI' in self.data,
            'aircrafts': aircrafts,
            'code': code,
            'fuel': int(self.data['Fuel']),
            'with_parachutes': 'Parachute' not in self.data,
            'count': count,
            'weapons': self.data['weapons'],
        })

        return {self.output_key: self.flight_info}

    def _get_skill(self, aircraft_id):
        if 'Skill' in self.data:
            return to_skill(self.data['Skill'])
        else:
            return to_skill(self.data['Skill{:}'.format(aircraft_id)])

    def _has_markings(self, aircraft_id):
            return 'numberOn{:}'.format(aircraft_id) not in self.data

    def _get_skin(self, prefix, aircraft_id):
        return self.data.get('{:}{:}'.format(prefix, aircraft_id))

    def _get_spawn_object_id(self, aircraft_id):
            return self.data.get('spawn{:}'.format(aircraft_id))


class FlightRouteParser(CollectingParser):
    """
    Parses ``*_Way`` section.
    View :ref:`detailed description <flight-route-section>`.
    """
    input_suffix = "_Way"
    output_prefix = 'flight_route_'

    def check_section_name(self, section_name):
        return section_name.endswith(self.input_suffix)

    def _extract_flight_code(self, section_name):
        return section_name[:-len(self.input_suffix)]

    def init_parser(self, section_name):
        super(FlightRouteParser, self).init_parser(section_name)
        flight_code = self._extract_flight_code(section_name)
        self.output_key = "{}{}".format(self.output_prefix, flight_code)
        self.route_point = None

    def parse_line(self, line):
        params = line.split()
        type_code, params = params[0], params[1:]
        if type_code == ROUTE_POINT_EXTRA_PARAMETERS_MARK:
            self._parse_options(params)
        else:
            self._finalize_current_point()
            pos, speed, params = params[0:3], params[3], params[4:]
            self.route_point = {
                'type': RoutePointTypes.get_by_value(type_code),
                'pos': Point3D(*pos),
                'speed': float(speed),
            }
            self._parse_extra(params)

    def _parse_options(self, params):
        try:
            cycles, timeout, angle, side_size, altitude_difference = params
            self.route_point.update({
                'options': {
                    'cycles': int(cycles),
                    'timeout': int(timeout),
                },
                'pattern': {
                    'angle': int(angle),
                    'side_size': int(side_size),
                    'altitude_difference': int(altitude_difference),
                },
            })
        except ValueError:
            delay, spacing = params[1:3]
            self.route_point.update({
                'options': {
                    'delay': int(delay),
                    'spacing': int(spacing),
                },
            })

    def _parse_extra(self, params):
        try:
            target_id, target_route_point, radio_silence = params[:3]
            params = params[3:]
            self.route_point.update({
                'target': {
                    'id': target_id,
                    'route_point': int(target_route_point),
                },
            })
            if self.route_point['type'] is RoutePointTypes.normal:
                self.route_point['type'] = RoutePointTypes.air_attack
        except ValueError:
            radio_silence = params[0]
            params = params[1:]
        finally:
            formation = Formations.get_by_value(params[0]) if params else None
            radio_silence = radio_silence == ROUTE_POINT_RADIO_SILENCE
            self.route_point.update({
                'radio_silence': radio_silence,
                'formation': formation,
            })

    def process_data(self):
        self._finalize_current_point()
        return {self.output_key: self.data}

    def _finalize_current_point(self):
        if self.route_point:
            self.data.append(self.route_point)


class FileParser(object):
    """
    Parses a whole mission file.
    View :ref:`detailed description <file-parser>`.
    """

    def __init__(self):
        self.parsers = [
            MainParser(),
            SeasonParser(),
            WeatherParser(),
            RespawnTimeParser(),
            MDSParser(),
            MDSScoutsParser(),
            ChiefsParser(),
            ChiefRoadParser(),
            NStationaryParser(),
            BuildingsParser(),
            TargetParser(),
            BornPlaceParser(),
            BornPlaceAircraftsParser(),
            BornPlaceAirForcesParser(),
            StaticCameraParser(),
            FrontMarkerParser(),
            RocketParser(),
            WingParser(),
            FlightRouteParser(),
        ]
        self.flight_info_parser = FlightInfoParser()

    def parse(self, mission):
        if isinstance(mission, six.string_types):
            with open(mission, 'r') as f:
                return self.parse_stream(f)
        else:
            return self.parse_stream(mission)

    def parse_stream(self, stream):
        parser = None
        self.data = {}

        def _raise_error(message, traceback):
            error = MissionParsingError(message)
            six.reraise(MissionParsingError, error, traceback)

        def _finalize_parser():
            if parser:
                try:
                    self.data.update(parser.stop())
                except Exception:
                    error_type, original_msg, traceback = sys.exc_info()
                    _raise_error(original_msg, traceback)

        for line in stream:
            line = line.strip()
            if self.is_section_name(line):
                _finalize_parser()
                section_name = self.get_section_name(line)
                parser = self.get_parser(section_name)
            elif parser:
                try:
                    parser.parse_line(line)
                except Exception:
                    error_type, original_msg, traceback = sys.exc_info()
                    msg = (
                        "{} (in line \"{}\")"
                    ).format(
                        original_msg, line
                    )
                    _raise_error(msg, traceback)

        _finalize_parser()
        return self.process_data()

    def is_section_name(self, line):
        return line.startswith('[') and line.endswith(']')

    def get_section_name(self, line):
        return line.strip('[]')

    def get_parser(self, section_name):
        flights = self.data.get('flights')
        if flights is not None and self.flight_info_parser.start(section_name):
            return self.flight_info_parser
        for parser in self.parsers:
            if parser.start(section_name):
                return parser
        return None

    def process_data(self):
        return {
            'location_loader': self.data.pop('location_loader'),
            'conditions': self._get_conditions(),
            'objects': self._get_objects(),
            'targets': self.data.pop('targets', []),
            'player': self.data.pop('player'),
        }

    def _get_conditions(self):
        return {
            'time_info': self._get_time_info(),
            'meteorology': self._get_meteorology(),
            'scouting': self._get_scouting(),
            'radar': self.data['conditions'].pop('radar'),
            'communication': self.data['conditions'].pop('communication'),
            'home_bases': self.data['conditions'].pop('home_bases'),
            'crater_visibility_muptipliers': self.data['conditions'].pop('crater_visibility_muptipliers'),
            'respawn_time': self.data.pop('respawn_time'),
        }

    def _get_time_info(self):
        timestamp = datetime.datetime.combine(self.data['date'],
                                              self.data['time']['value'])
        return {
            'timestamp': timestamp,
            'is_fixed': self.data['time']['is_fixed'],
        }

    def _get_meteorology(self):
        return dict(
            {
                'weather': self.data.pop('weather_conditions'),
                'cloud_base': self.data.pop('cloud_base'),
            },
            **self.data.pop('weather')
        )

    def _get_scouting(self):
        data = self.data['conditions'].pop('scouting')
        keys = filter(
            lambda x: x.startswith(MDSScoutsParser.output_prefix),
            self.data.keys()
        )
        data['scouts'] = {
            self.data[key]['belligerent']: self.data[key]['aircrafts']
            for key in keys
        }
        return data

    def _get_objects(self):
        return {
            'moving_units': self._get_moving_units(),
            'flights': self._get_flights(),
            'home_bases': self._get_home_bases(),
            'stationary': self.data.pop('stationary', []),
            'buildings': self.data.pop('buildings', []),
            'cameras': self.data.pop('cameras', []),
            'markers': self.data.pop('markers', []),
            'rockets': self.data.pop('rockets', []),
        }

    def _get_moving_units(self):
        units = self.data.pop('moving_units', [])
        for unit in units:
            key = "{}{}".format(ChiefRoadParser.output_prefix, unit['id'])
            unit['route'] = self.data.pop(key)
        return units

    def _get_flights(self):
        keys = self.data.pop('flights', [])
        flights = [self.data.pop(key) for key in keys]
        for flight in flights:
            key = "{}{}".format(FlightRouteParser.output_prefix, flight['id'])
            flight['route'] = self.data.pop(key)
        return flights

    def _get_home_bases(self):
        home_bases = self.data.pop('home_bases', [])
        for i, home_base in enumerate(home_bases):
            key = "{}{}".format(BornPlaceAircraftsParser.output_prefix, i)
            home_base['aircraft_limitations']['allowed_aircrafts'] = self.data.pop(key, [])

            key = "{}{}".format(BornPlaceAirForcesParser.output_prefix, i)
            home_base['allowed_air_forces'] = self.data.pop(key, [])
        return home_bases
