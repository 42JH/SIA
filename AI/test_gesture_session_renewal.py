import unittest
from unittest.mock import Mock, patch

from be_link import AgentLink


class GestureDispatchTests(unittest.TestCase):
    def setUp(self):
        with patch('be_link.read_runtime', return_value=None):
            self.link = AgentLink()
        self.link._send = Mock(return_value=True)
        self.link.call = Mock(return_value=(True, {}))

    def test_gesture_dispatch_does_not_extend_session_in_ai(self):
        self.assertFalse(hasattr(self.link, 'gesture_renewal_policy'))
        self.assertTrue(self.link.send_event('gesture_exec', {'name': 'Closed_Fist'}))
        self.link.call.assert_not_called()
        self.link._send.assert_called_once_with({
            'type': 'gesture_exec', 'data': {'name': 'Closed_Fist'}})

    def test_non_gesture_events_are_forwarded_without_mcp_calls(self):
        self.assertTrue(self.link.send_event('notice', {'message': 'test'}))
        self.link.call.assert_not_called()
        self.link._send.assert_called_once_with({
            'type': 'notice', 'data': {'message': 'test'}})


if __name__ == '__main__':
    unittest.main()
