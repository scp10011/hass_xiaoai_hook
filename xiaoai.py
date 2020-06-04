import asyncio
import json
import logging
from datetime import timedelta

import voluptuous as vol

from homeassistant.loader import bind_hass
from homeassistant.const import STATE_ON, STATE_OFF
from homeassistant.components.http import HomeAssistantView
from homeassistant.helpers.entity import Entity
from homeassistant.helpers.entity_component import EntityComponent
from homeassistant.const import (
    CONF_NAME,
    CONF_HOST,
    CONF_PORT,
    CONF_TOKEN,
    ATTR_ENTITY_ID,
)
import homeassistant.helpers.config_validation as cv

import rpc

_LOGGER = logging.getLogger(__name__)

MAIN = "xiaoai_hook"
DOMAIN = "xiaoai_hook"
CONF_KEYWORD = "keyword"
_keyword = None
_hass = None
ATTR_MODEL = "model"
SCAN_INTERVAL = timedelta(seconds=10)
ENTITY_ID_FORMAT = DOMAIN + ".{}"

METHOD = {"ch", "prev", "next", "play", "pause", "toggle", "resume"}

SERVICE_SET_VOLUME_UP = "set_volume_up"
SERVICE_SET_VOLUME_DOWN = "set_volume_down"
SERVICE_SET_VOLUME = "set_volume"
SERVICE_XIAOAI_TTS = "xiaoai_tts"
SERVICE_PLAY_CONTROL = "play_control"

ATTR_VOLUME = "v"

XIAOAI_SERVICE_SCHEMA = vol.Schema({vol.Optional(ATTR_ENTITY_ID): cv.entity_ids})
SERVICE_SCHEMA_VOLUME = XIAOAI_SERVICE_SCHEMA.extend(
    {vol.Required(ATTR_VOLUME): vol.All(vol.Coerce(int), vol.In(METHOD))}
)

SERVICE_SCHEMA_CONTROL = XIAOAI_SERVICE_SCHEMA.extend(
    {vol.Required(ATTR_VOLUME): vol.All(vol.Coerce(str), vol.Clamp(min=0, max=100))}
)
SERVICE_TO_METHOD = {
    SERVICE_SET_VOLUME_UP: {"method": "set_volume_up"},
    SERVICE_SET_VOLUME_DOWN: {"method": "set_volume_down"},
    SERVICE_SET_VOLUME: {"method": "set_volume", "schema": SERVICE_SCHEMA_VOLUME},
    SERVICE_XIAOAI_TTS: {"method": "xiaoai_tts"},
    SERVICE_PLAY_CONTROL: {"method": "play_control", "schema": SERVICE_SCHEMA_CONTROL},
}


@bind_hass
def is_on(hass, entity_id: str = None) -> bool:
    if hass.states.get(entity_id):
        return True
    else:
        return False


async def async_setup(hass, config):
    """Set up the Xiaoai component."""
    global _hass, _keyword
    _hass = hass
    component = hass.data[DOMAIN] = EntityComponent(
        _LOGGER, DOMAIN, hass, SCAN_INTERVAL
    )
    XiaoaiKeyword.keyword = config[DOMAIN].get(CONF_KEYWORD, "")
    hass.http.register_view(XiaoaiKeyword)
    await component.async_setup(config)
    return True


async def async_setup_entry(hass, entry):
    """Set up a config entry."""
    return await hass.data[DOMAIN].async_setup_entry(entry)


async def async_unload_entry(hass, entry):
    """Unload a config entry."""
    return await hass.data[DOMAIN].async_unload_entry(entry)


async def async_setup_platform(hass, config, async_add_entities, discovery_info=None):
    ip = config[CONF_HOST]
    unique_id = "{}-{}".format(MAIN, ip.replace(".", "_"))
    name = config[CONF_NAME]
    port = int(config.get(CONF_PORT, 18888))
    token = config.get(CONF_TOKEN, None)
    xiaoai_rpc = rpc.jsonRPC(ip, port, token=token)
    device = XiaoAi(name, xiaoai_rpc, unique_id)
    hass.data[DOMAIN][ip] = device
    async_add_entities([device], update_before_add=True)

    async def async_service_handler(service):
        """Map services to methods on XiaomiToiletlid."""
        method = SERVICE_TO_METHOD.get(service.service)
        params = service.data.copy()
        entity_ids = params.pop(ATTR_ENTITY_ID, hass.data[DOMAIN].values())
        update_tasks = []
        for device in filter(
                lambda x: x.entity_id in entity_ids, hass.data[DOMAIN].values()
        ):
            if not hasattr(device, method["method"]):
                continue
            await getattr(device, method["method"])(**params)
            update_tasks.append(device.async_update_ha_state(True))

        if update_tasks:
            await asyncio.wait(update_tasks)

    for service in SERVICE_TO_METHOD:
        schema = SERVICE_TO_METHOD[service].get(
            "schema", XIAOAI_SERVICE_SCHEMA
        )
        hass.services.async_register(
            DOMAIN, service, async_service_handler, schema=schema
        )


class XiaoaiKeyword(HomeAssistantView):
    """View to handle Configuration requests."""

    url = "/xiaoai_hook/keyword"
    name = "keyword"
    requires_auth = False

    async def get(self, request):
        global _keyword
        return _keyword


class XiaoaiEvent(HomeAssistantView):
    url = "/xiaoai_hook/event"
    name = "keyword"
    requires_auth = False

    async def post(self, request):
        """Handle request"""
        post = await request.post()
        answer = post.get("answer")
        res_data = json.loads(post.get("res"))
        querys = res_data["response"]["answer"][0]["text"]
        intention = res_data["response"]["answer"][0]["intention"]
        _hass.bus.fire(f"xiaoai_select_event", {"msg": querys, "default": answer})

        return ""


class XiaoAi(Entity):
    def __init__(self, name, rpc, unique_id):
        """Initialize the generic Xiaomi device."""
        self._name = name
        self._device = rpc
        self._model = MAIN
        self._unique_id = unique_id

        self._state = None
        self._available = False
        self._state_attrs = {ATTR_MODEL: self._model, "code": -1}

    @property
    def unique_id(self) -> str:
        """Return an unique ID."""
        return self._unique_id

    @property
    def name(self) -> str:
        """Return the name of the device if any."""
        return self._name

    @property
    def available(self):
        """Return true when state is known."""
        return self._available

    @property
    def device_state_attributes(self):
        """Return the state attributes of the device."""
        return self._state_attrs

    @property
    def state(self) -> str:
        """Return the state."""
        return STATE_ON if self.is_on else STATE_OFF

    @property
    def icon(self) -> str:
        """Return the icon to use in the frontend, if any."""
        return "mdi:speaker"

    @property
    def is_on(self) -> bool:
        """Return true if device is on."""
        return self._state

    from homeassistant.components import yeelight

    async def async_update(self):
        """Fetch state from the device."""
        try:
            self._available = False
            state = await self.hass.async_add_executor_job(self._device.status)
            _LOGGER.debug("Got new state: %s", state)
            self._state_attrs.update(state)
            self._state = state["code"] == 0
            self._available = True
        except Exception as ex:
            _LOGGER.error("Got exception while fetching the state: %s", ex)

    async def set_volume_up(self) -> bool:
        try:
            obj = await self.hass.async_add_executor_job(
                lambda: self._device.volume("up")
            )
            return obj.get("code") == 0
        except Exception as exc:
            _LOGGER.error("set volume up failure: %s", exc)
            return False

    async def set_volume_down(self) -> bool:
        try:
            obj = await self.hass.async_add_executor_job(
                lambda: self._device.volume("down")
            )
            return obj.get("code") == 0
        except Exception as exc:
            _LOGGER.error("set volume down failure: %s", exc)
            return False

    async def set_volume(self, v: int) -> bool:
        try:
            obj = await self.hass.async_add_executor_job(lambda: self._device.volume(v))
            return obj.get("code") == 0
        except Exception as exc:
            _LOGGER.error("set volume down failure: %s", exc)
            return False

    async def xiaoai_tts(self, msg: str) -> bool:
        msg = msg.replace("&", "")
        try:
            obj = await self.hass.async_add_executor_job(lambda: self._device.tts(msg))
            return obj.get("code") == 0
        except Exception as exc:
            _LOGGER.error("tts failure: %s", exc)
            return False

    async def play_control(self, method: str) -> bool:
        try:
            obj = await self.hass.async_add_executor_job(
                lambda: self._device.control(method)
            )
            return obj.get("code") == 0
        except Exception as exc:
            _LOGGER.error("play control failure: %s", exc)
            return False
