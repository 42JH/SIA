import json
import time
import unittest
from unittest.mock import Mock, patch

from be_link import AgentLink
from hands import HoldToggle


class RenewalTests(unittest.TestCase):
    def setUp(self):
        with patch('be_link.read_runtime', return_value=None):
            self.link = AgentLink()
        self.link.connected = self.link.gesture_ready = True
        self.link._send = Mock(return_value=True)
        self.link.call = Mock(return_value=(True, {}))
        self.rows = [dict(id=1, name='Closed_Fist', context=None, enabled=True,
                          steps=[dict(tool='screen.capture')])]
        self.policy = self.link.gesture_renewal_policy
        self.policy.read_json = lambda p: (
            [dict(name='screen.capture', sessionRequired=True)] if '/tools' in p
            else dict(items=self.rows, total=len(self.rows)))
        self.policy.refresh()
        self.foreground = patch('be_link.foreground_context_chain', return_value=[])
        self.foreground.start()
        self.addCleanup(self.foreground.stop)

    def session(self, state='ACTIVE', remaining=15, ident=1):
        self.link._on_event(json.dumps(dict(type='session_state', data=dict(
            state=state, sessionId=ident, deadlineMs=(time.time()+remaining)*1000))))

    def send(self):
        return self.link.send_event('gesture_exec', dict(name='Closed_Fist'))

    def test_twenty_commands_extend_before_send(self):
        self.session()
        order = []
        self.link.call.side_effect = lambda tool: (order.append(tool) or (True, {}))
        self.link._send.side_effect = lambda event: (order.append(event['type']) or True)
        for _ in range(20):
            self.assertTrue(self.send())
        self.assertEqual(order, ['session.extend', 'gesture_exec'] * 20)

    def test_inactive_and_expired_preserve_be_execution_gate(self):
        for state, remaining in [('PASSIVE', 15), ('ACTIVE', -1)]:
            self.session(state, remaining)
            self.assertTrue(self.send())
        self.link.call.assert_not_called()
        self.assertTrue(all(c.args[0]['type']=='gesture_exec' for c in self.link._send.call_args_list))

    def test_no_renewal_for_invalid_mapping(self):
        self.session()
        original = self.rows[0].copy()
        for update in [dict(enabled=False), dict(steps=[]), dict(steps=[dict(tool='unknown')]),
                       dict(name='other')]:
            self.rows[:] = [dict(original, **update)]
            self.policy.refresh()
            self.send()
        self.link.call.assert_not_called()

    def test_stale_or_invalidated_policy_skips_renewal(self):
        self.session()
        self.policy.clock = lambda: time.monotonic()+4
        self.send()
        self.policy.invalidate()
        self.send()
        self.link.call.assert_not_called()

    def test_failure_blocks_without_retry(self):
        self.session()
        for ok in [False, None]:
            self.link.call.return_value = (ok, {})
            self.assertFalse(self.send())
        self.link._send.assert_not_called()

    def test_session_end_or_replacement_during_extension(self):
        for state, ident in [('PASSIVE', 1), ('ACTIVE', 2)]:
            self.session()
            self.link.call.side_effect = lambda tool: (self.session(state, ident=ident) or (True, {}))
            self.assertFalse(self.send())
        self.link._send.assert_not_called()

    def test_disconnect_during_extension(self):
        self.session()
        def extend(tool):
            self.link.connected = False
            return True, {}
        self.link.call.side_effect = extend
        self.assertFalse(self.send())
        self.link._send.assert_not_called()

    def test_held_pose_only_one_renewal(self):
        self.session(remaining=60)
        toggle = HoldToggle(hold_s=0.8, cooldown_s=2.0, grace_s=0.55)
        for frame in range(900):
            if toggle.update(True, frame/30):
                self.send()
        self.link.call.assert_called_once_with('session.extend')

    def test_context_disabled_override_and_default(self):
        self.rows.append(dict(self.rows[0], id=2, context='video', enabled=False))
        self.policy.refresh()
        self.assertFalse(self.policy.can_renew('Closed_Fist', None, ['youtube','video']))
        self.assertTrue(self.policy.can_renew('Closed_Fist', None, []))
        self.assertFalse(self.policy.can_renew('Closed_Fist', None, None))

    def test_other_events_do_not_renew(self):
        self.session()
        self.link.send_event('notice', dict(message='test'))
        self.link.call.assert_not_called()

    def test_reconnect_requires_session_sync(self):
        self.session()
        self.link._gesture_session_synced = False
        self.send()
        self.link.call.assert_not_called()

    def test_mapping_change_invalidates_cache(self):
        self.session()
        self.link._on_event(json.dumps(dict(type='gesture_toggled', data={})))
        self.send()
        self.link.call.assert_not_called()


if __name__ == '__main__':
    unittest.main()
