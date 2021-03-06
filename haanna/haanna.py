"""
Plugwise Anna HomeAssistant component
"""
import requests
import xml.etree.cElementTree as Etree
import json
from requests.exceptions import HTTPError

USERNAME = ''
PASSWORD = ''
ANNA_ENDPOINT = ''
ANNA_PING_ENDPOINT = '/ping'
ANNA_DOMAIN_OBJECTS_ENDPOINT = '/core/domain_objects'
ANNA_LOCATIONS_ENDPOINT = '/core/locations'
ANNA_APPLIANCES = '/core/appliances'
ANNA_RULES = '/core/rules'


class Haanna(object):

    def __init__(self, username, password, host, port):
        """Constructor for this class"""
        self.set_credentials(username, password)
        self.set_anna_endpoint('http://' + host + ':' + str(port))

    @staticmethod
    def ping_anna_thermostat():
        """Ping the thermostat to see if it's online"""
        r = requests.get(ANNA_ENDPOINT + ANNA_PING_ENDPOINT, auth=(USERNAME, PASSWORD), timeout=10)

        if r.status_code != 404:
            raise ConnectionError("Could not connect to the gateway.")

        return True

    @staticmethod
    def get_domain_objects():
        r = requests.get(ANNA_ENDPOINT + ANNA_DOMAIN_OBJECTS_ENDPOINT, auth=(USERNAME, PASSWORD), timeout=10)

        if r.status_code != requests.codes.ok:
            raise ConnectionError("Could not get the domain objects.")

        return Etree.fromstring(r.text)

    def __is_legacy_anna(self,root):
        """Detect Anna legacy version based on different domain_objects structure """
        return root.find("appliance[type='thermostat']/location") is None

    def get_presets(self, root):
        """Gets the presets from the thermostat"""
        if self.__is_legacy_anna(root):
            return self.__get_preset_dictionary_v1(root)
        else:      
            rule_id = self.get_rule_id_by_name(root, 'Thermostat presets')

            if rule_id is None:
                raise RuleIdNotFoundException("Could not find the rule id.")

            presets = self.get_preset_dictionary(root, rule_id)
            return presets

    def get_mode(self, root):
        """Gets the mode the thermostat is in (active schedule true or false)"""
        if self.__is_legacy_anna(root):
            return root.find("module/services/schedule_state/measurement").text =='on'
        else:
            rule_id = self.get_rule_id_by_template_tag(root, 'zone_preset_based_on_time_and_presence_with_override')

            if rule_id is None:
                raise RuleIdNotFoundException("Could not find the rule id.")

            mode = self.get_active_mode(root, rule_id)
            return mode

    def set_preset(self,root, preset):
        """Sets the given preset on the thermostat"""
        if self.__is_legacy_anna(root):
            self.__set_preset_v1
        else:                  
            location_id = root.find("appliance[type='thermostat']/location").attrib['id']

            locations_root = Etree.fromstring(
                requests.get(
                    ANNA_ENDPOINT + ANNA_LOCATIONS_ENDPOINT,
                    auth=(USERNAME, PASSWORD),
                    timeout=10
                ).text
            )

            current_location = locations_root.find("location[@id='" + location_id + "']")
            location_name = current_location.find("name").text
            location_type = current_location.find("type").text

            r = requests.put(
                ANNA_ENDPOINT + ANNA_LOCATIONS_ENDPOINT + ';id=' + location_id,
                auth=(USERNAME, PASSWORD),
                data='<locations>' +
                    '<location id="' + location_id + '">' +
                    '<name>' + location_name + '</name>' +
                    '<type>' + location_type + '</type>' +
                    '<preset>' + preset + '</preset>' +
                    '</location>' +
                    '</locations>',
                headers={'Content-Type': 'text/xml'},
                timeout=10
            )

            if r.status_code != requests.codes.ok:
                raise CouldNotSetPresetException("Could not set the given preset: " + r.text)

            return r.text

    def __set_preset_v1(self, root, preset):
        """Sets the given preset on the thermostat for V1"""
        rule = root.find("rule/directives/when/then[@icon='"+preset+"'].../.../...")
        if rule is None:
            raise CouldNotSetPresetException("Could not find preset '" + preset + "'")
        else:
            rule_id = rule.attrib['id']
            r = requests.put(
                ANNA_ENDPOINT +
                ANNA_RULES,                
                auth=(USERNAME, PASSWORD),
                data='<rules>' +
                    '<rule id="'+ rule_id+'">' +
                    '<active>true</active>' +
                    '</rule>' +
                    '</rules>',
                headers={'Content-Type': 'text/xml'},
                timeout=10
            )
            if r.status_code != requests.codes.ok:
                raise CouldNotSetPresetException("Could not set the given preset: " + r.text)
            return r.text


    def get_heating_status(self, root):
        """Gets the active heating status"""
        if self.__is_legacy_anna(root):   
            return root.find("appliance[type='heater_central']/logs/point_log[type='boiler_state']/period/measurement").text == 'on'
        else:
            if root.find("appliance[type='heater_central']/logs/point_log[type='central_heating_state']/period/measurement").text == 'on':
                return True
            else:
                return False

    def get_current_preset(self, root):
        """Gets the current active preset"""
        if self.__is_legacy_anna(root):
            active_rule = root.find("rule[active='true']")
            if active_rule is None:
                """"No active preset"""
                return ""
            else:
                return active_rule.find("directives/when/then").attrib['icon']
        else:        
            location_id = root.find("appliance[type='thermostat']/location").attrib['id']
            return root.find("location[@id='" + location_id + "']/preset").text

    def get_temperature(self, root):
        """Gets the temperature from the thermostat"""
        point_log_id = self.get_point_log_id(root, 'temperature')
        measurement = self.get_measurement_from_point_log(root, point_log_id)

        return float(measurement)

    def get_target_temperature(self, root):
        """Gets the target temperature from the thermostat"""
        target_temperature_log_id = self.get_point_log_id(root, 'thermostat')
        measurement = self.get_measurement_from_point_log(root, target_temperature_log_id)

        return float(measurement)

    def get_outdoor_temperature(self, root):
        """Gets the temperature from the thermostat"""
        outdoor_temperature_log_id = self.get_point_log_id(root, 'outdoor_temperature')
        measurement = self.get_measurement_from_point_log(root, outdoor_temperature_log_id)

        return float(measurement)

    def __get_temperature_uri(self,root):
        """Determine the set_temperature uri for different versions of Anna"""
        if self.__is_legacy_anna(root):
            appliance_id = root.find("appliance[type='thermostat']").attrib['id']
            return ANNA_APPLIANCES + ';id=' + appliance_id + '/thermostat'
        else:
            location_id = root.find("appliance[type='thermostat']/location").attrib['id']
            thermostat_functionality_id = root.find(
                "location[@id='" + location_id + "']/actuator_functionalities/thermostat_functionality"
            ).attrib['id']
        
            return ANNA_LOCATIONS_ENDPOINT +  ';id=' + location_id + '/thermostat;id=' + thermostat_functionality_id
                
    def set_temperature(self, root, temperature):
        """Sends a set request to the temperature with the given temperature"""
        uri = self.__get_temperature_uri(root)

        temperature = str(temperature)

        r = requests.put(
            ANNA_ENDPOINT +
            uri,                
            auth=(USERNAME, PASSWORD),
            data='<thermostat_functionality><setpoint>' + temperature + '</setpoint></thermostat_functionality>',
            headers={'Content-Type': 'text/xml'},
            timeout=10
        )

        if r.status_code != requests.codes.ok:
            CouldNotSetTemperatureException("Could not set the temperature." + r.text)

        return r.text

    @staticmethod
    def set_credentials(username, password):
        """Sets the username and password variables"""
        global USERNAME
        global PASSWORD
        USERNAME = username
        PASSWORD = password

    @staticmethod
    def get_credentials():
        return {'username': USERNAME, 'password': PASSWORD}

    @staticmethod
    def set_anna_endpoint(endpoint):
        """Sets the endpoint where the Anna resides on the network"""
        global ANNA_ENDPOINT
        ANNA_ENDPOINT = endpoint

    @staticmethod
    def get_anna_endpoint():
        return ANNA_ENDPOINT

    @staticmethod
    def get_point_log_id(root, log_type):
        """Gets the point log ID based on log type"""
        return root.find("module/services/*[@log_type='" + log_type + "']/functionalities/point_log").attrib['id']

    @staticmethod
    def get_measurement_from_point_log(root, point_log_id):
        """Gets the measurement from a point log based on point log ID"""
        return root.find("*/logs/point_log[@id='" + point_log_id + "']/period/measurement").text

    @staticmethod
    def get_rule_id_by_name(root, rule_name):
        """Gets the rule ID based on name"""
        rules = root.findall("rule")
        for rule in rules:
            if rule.find("name").text == rule_name:
                return rule.attrib['id']

    @staticmethod
    def get_rule_id_by_template_tag(root, rule_name):
        """Gets the rule ID based on template_tag"""
        schema_ids = []
        rules = root.findall("rule")
        for rule in rules:
            if rule.find("template").attrib['tag'] == rule_name:
                schema_ids.append(rule.attrib['id'])
        return schema_ids

    @staticmethod
    def get_preset_dictionary(root, rule_id):
        """Gets the presets from a rule based on rule ID and returns a dictionary with all the key-value pairs"""
        preset_dictionary = {}
        directives = root.find("rule[@id='" + rule_id + "']/directives")
        for directive in directives:
            preset_dictionary[directive.attrib['preset']] = float(directive.find("then").attrib['setpoint'])
        return preset_dictionary

    @staticmethod
    def __get_preset_dictionary_v1(root):
        """Gets the presets and returns a dictionary with all the key-value pairs"""
        """Example output: {'away': 17.0, 'home': 20.0, 'vacation': 15.0, 'no_frost': 10.0, 'asleep': 15.0}"""
        preset_dictionary = {}
        directives = root.findall("rule/directives/when/then")
        for directive in directives:
            preset_dictionary[directive.attrib['icon']] = float(directive.attrib['temperature'])
        return preset_dictionary

    @staticmethod
    def get_active_mode(root, schema_ids):
        """Gets the mode from a (list of) rule id(s)"""
        active=False
        for schema_id in schema_ids:
            if root.find("rule[@id='" + schema_id + "']/active").text == 'true':
                active=True
                break
        return active


class AnnaException(Exception):
    def __init__(self, arg1, arg2=None):
        """Base exception for interaction with the Anna gateway"""
        self.arg1 = arg1
        self.arg2 = arg2
        super(AnnaException, self).__init__(arg1)


class RuleIdNotFoundException(AnnaException):
    """Raise an exception for when the rule id is not found in the direct objects"""
    pass


class CouldNotSetPresetException(AnnaException):
    """Raise an exception for when the preset can not be set"""
    pass


class CouldNotSetTemperatureException(AnnaException):
    """Raise an exception for when the temperature could not be set"""
    pass
