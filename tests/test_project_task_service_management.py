from datetime import timedelta

from odoo.exceptions import AccessError, UserError
from odoo.fields import Datetime
from odoo.tests.common import TransactionCase, tagged


@tagged('post_install', '-at_install')
class TestProjectTaskServiceManagement(TransactionCase):
    """Covers the item-55 checklist: START/PAUSE/RESUME, one-active-
    session-per-employee, DONE/APPROVE/REJECT, TRANSFER (including
    optional reason), hourly/per-task billing, Actual Time/Variance,
    and the security-sensitive operations an ordinary employee must
    never be able to perform.

    Every fixture (users, employees, partner, project) is created
    fresh in setUpClass - nothing here depends on demo data being
    loaded or on any particular database ID, per the Part 11
    instruction not to write ID-dependent tests.
    """

    @classmethod
    def setUpClass(cls):
        super().setUpClass()

        Users = cls.env['res.users'].with_context(
            no_reset_password=True,
            mail_create_nolog=True,
            mail_create_nosubscribe=True,
            mail_notrack=True,
        )
        Employee = cls.env['hr.employee']

        project_user_group = cls.env.ref('project.group_project_user')
        project_manager_group = cls.env.ref('project.group_project_manager')

        cls.manager_user = Users.create({
            'name': 'Test PM',
            'login': 'test_pm_ptsm',
            'email': 'test_pm_ptsm@example.com',
            'groups_id': [(6, 0, [project_user_group.id, project_manager_group.id])],
        })
        cls.manager_employee = Employee.create({
            'name': 'Test PM',
            'user_id': cls.manager_user.id,
        })

        cls.employee_a_user = Users.create({
            'name': 'Employee A',
            'login': 'test_employee_a_ptsm',
            'email': 'employee_a_ptsm@example.com',
            'groups_id': [(6, 0, [project_user_group.id])],
        })
        cls.employee_a = Employee.create({
            'name': 'Employee A',
            'user_id': cls.employee_a_user.id,
        })

        cls.employee_b_user = Users.create({
            'name': 'Employee B',
            'login': 'test_employee_b_ptsm',
            'email': 'employee_b_ptsm@example.com',
            'groups_id': [(6, 0, [project_user_group.id])],
        })
        cls.employee_b = Employee.create({
            'name': 'Employee B',
            'user_id': cls.employee_b_user.id,
        })

        cls.customer = cls.env['res.partner'].create({'name': 'Test Customer PTSM'})

        cls.project = cls.env['project.project'].create({
            'name': 'Test Project PTSM',
            'partner_id': cls.customer.id,
            'project_manager_id': cls.manager_employee.id,
        })

    # -- Fixture helpers --------------------------------------------

    def _create_task(self, **overrides):
        vals = {
            'name': 'Test Task',
            'project_id': self.project.id,
            'user_ids': [(6, 0, [self.employee_a_user.id])],
            'estimated_time': 5.0,
        }
        vals.update(overrides)
        return self.env['project.task'].with_user(self.manager_user).create(vals)

    def _create_closed_session(self, task, employee, user, hours, state='completed'):
        """Bypass Start/Pause (and their own record rule) to set up a
        session with a precisely controlled duration, via sudo() - this
        is fixture setup, not the thing under test.
        """
        start = Datetime.now()
        return self.env['project.task.work.session'].sudo().create({
            'task_id': task.id,
            'employee_id': employee.id,
            'user_id': user.id,
            'start_datetime': start,
            'end_datetime': start + timedelta(hours=hours),
            'state': state,
        })

    # -- START / PAUSE / RESUME --------------------------------------

    def test_start_creates_exactly_one_running_session(self):
        task = self._create_task()
        task.with_user(self.employee_a_user).action_start_work()
        sessions = self.env['project.task.work.session'].search([
            ('task_id', '=', task.id), ('employee_id', '=', self.employee_a.id),
        ])
        self.assertEqual(len(sessions), 1)
        self.assertEqual(sessions.state, 'running')
        self.assertFalse(sessions.end_datetime)

    def test_one_active_session_per_employee_across_tasks(self):
        task1 = self._create_task(name='Task 1')
        task2 = self._create_task(name='Task 2')
        task1.with_user(self.employee_a_user).action_start_work()
        with self.assertRaises(UserError):
            task2.with_user(self.employee_a_user).action_start_work()

    def test_concurrent_employees_same_task_both_allowed(self):
        task = self._create_task(user_ids=[
            (6, 0, [self.employee_a_user.id, self.employee_b_user.id]),
        ])
        task.with_user(self.employee_a_user).action_start_work()
        task.with_user(self.employee_b_user).action_start_work()
        running = self.env['project.task.work.session'].search([
            ('task_id', '=', task.id), ('state', '=', 'running'),
        ])
        self.assertEqual(len(running), 2)

    def test_pause_only_closes_current_employees_own_session(self):
        task = self._create_task(user_ids=[
            (6, 0, [self.employee_a_user.id, self.employee_b_user.id]),
        ])
        task.with_user(self.employee_a_user).action_start_work()
        task.with_user(self.employee_b_user).action_start_work()
        task.with_user(self.employee_a_user).action_pause_work()

        session_a = self.env['project.task.work.session'].search([
            ('task_id', '=', task.id), ('employee_id', '=', self.employee_a.id),
        ])
        session_b = self.env['project.task.work.session'].search([
            ('task_id', '=', task.id), ('employee_id', '=', self.employee_b.id),
        ])
        self.assertEqual(session_a.state, 'paused')
        self.assertTrue(session_a.end_datetime)
        self.assertEqual(session_b.state, 'running')
        self.assertFalse(session_b.end_datetime)

    def test_resume_creates_new_session_without_modifying_previous(self):
        task = self._create_task()
        task.with_user(self.employee_a_user).action_start_work()
        task.with_user(self.employee_a_user).action_pause_work()

        first_session = self.env['project.task.work.session'].search([
            ('task_id', '=', task.id),
        ])
        first_start = first_session.start_datetime
        first_end = first_session.end_datetime

        task.with_user(self.employee_a_user).action_resume_work()

        sessions = self.env['project.task.work.session'].search([
            ('task_id', '=', task.id),
        ], order='id')
        self.assertEqual(len(sessions), 2)
        self.assertEqual(sessions[0].start_datetime, first_start)
        self.assertEqual(sessions[0].end_datetime, first_end)
        self.assertEqual(sessions[0].state, 'paused')
        self.assertEqual(sessions[1].state, 'running')
        self.assertFalse(sessions[1].end_datetime)

    # -- DONE / APPROVE / REJECT -------------------------------------

    def test_done_blocked_while_session_running(self):
        task = self._create_task()
        task.with_user(self.employee_a_user).action_start_work()
        task.with_user(self.employee_a_user).write({'employee_remarks': 'In progress.'})
        with self.assertRaises(UserError):
            task.with_user(self.employee_a_user).action_submit_for_verification()

    def test_done_blocked_without_project_manager_configured(self):
        # user_id is explicitly forced to False here: core Odoo's
        # project.project.user_id ("Project Manager") defaults to the
        # creating user, so without this override the project would
        # NOT actually end up manager-less, and this test would pass
        # for the wrong reason (or not test what it claims to).
        project_no_manager = self.env['project.project'].create({
            'name': 'No Manager Project PTSM',
            'partner_id': self.customer.id,
            'user_id': False,
        })
        self.assertFalse(project_no_manager.user_id)
        task = self.env['project.task'].with_user(self.manager_user).create({
            'name': 'Orphan Task',
            'project_id': project_no_manager.id,
            'user_ids': [(6, 0, [self.employee_a_user.id])],
        })
        task.with_user(self.employee_a_user).action_start_work()
        task.with_user(self.employee_a_user).action_pause_work()
        task.with_user(self.employee_a_user).write({'employee_remarks': 'Done.'})
        with self.assertRaises(UserError):
            task.with_user(self.employee_a_user).action_submit_for_verification()

    def test_full_done_approve_flow_locks_task(self):
        task = self._create_task()
        task.with_user(self.employee_a_user).action_start_work()
        task.with_user(self.employee_a_user).action_pause_work()
        task.with_user(self.employee_a_user).write({'employee_remarks': 'Completed.'})
        task.with_user(self.employee_a_user).action_submit_for_verification()
        self.assertEqual(task.verification_status, 'waiting')

        task.with_user(self.manager_user).write({'manager_remarks': 'Looks good.'})
        task.with_user(self.manager_user).action_approve_task()
        self.assertEqual(task.verification_status, 'approved')

        with self.assertRaises(UserError):
            task.with_user(self.employee_a_user).action_start_work()

    def test_self_approval_blocked(self):
        task = self._create_task(user_ids=[(6, 0, [self.manager_user.id])])
        task.with_user(self.manager_user).action_start_work()
        task.with_user(self.manager_user).action_pause_work()
        task.with_user(self.manager_user).write({'employee_remarks': 'Self work.'})
        task.with_user(self.manager_user).action_submit_for_verification()
        with self.assertRaises(UserError):
            task.with_user(self.manager_user).action_approve_task()

    def test_reject_requires_manager_remarks(self):
        task = self._create_task()
        task.with_user(self.employee_a_user).action_start_work()
        task.with_user(self.employee_a_user).action_pause_work()
        task.with_user(self.employee_a_user).write({'employee_remarks': 'Done.'})
        task.with_user(self.employee_a_user).action_submit_for_verification()
        with self.assertRaises(UserError):
            task.with_user(self.manager_user).action_reject_task()

    def test_reject_then_resubmit_preserves_all_time_and_history(self):
        task = self._create_task()
        task.with_user(self.employee_a_user).action_start_work()
        task.with_user(self.employee_a_user).action_pause_work()
        task.with_user(self.employee_a_user).write({'employee_remarks': 'First pass.'})
        task.with_user(self.employee_a_user).action_submit_for_verification()

        task.with_user(self.manager_user).write({'manager_remarks': 'Please fix.'})
        task.with_user(self.manager_user).action_reject_task()
        self.assertEqual(task.verification_status, 'rejected')

        task.with_user(self.employee_a_user).action_resume_work()
        task.with_user(self.employee_a_user).action_pause_work()
        task.with_user(self.employee_a_user).write({'employee_remarks': 'Second pass.'})
        task.with_user(self.employee_a_user).action_submit_for_verification()

        sessions = self.env['project.task.work.session'].search([('task_id', '=', task.id)])
        self.assertEqual(len(sessions), 2, 'Both work sessions must remain - none overwritten.')

        total_duration = sum(sessions.mapped('duration'))
        self.assertAlmostEqual(task.actual_work_hours, total_duration, places=6)

        history = self.env['project.task.verification'].search([('task_id', '=', task.id)])
        self.assertEqual(len(history), 2, 'Both verification cycles must remain in history.')
        self.assertEqual(sorted(history.mapped('result')), ['rejected', 'waiting'])

    # -- TRANSFER ------------------------------------------------------

    def test_transfer_with_blank_reason_succeeds(self):
        task = self._create_task()
        task.with_user(self.employee_a_user).action_start_work()

        wizard = self.env['project.task.transfer.wizard'].with_user(self.manager_user).create({
            'task_id': task.id,
            'from_employee_id': self.employee_a.id,
            'to_employee_id': self.employee_b.id,
            'reason': False,
        })
        wizard.action_transfer()

        self.assertIn(self.employee_b_user, task.user_ids)
        self.assertNotIn(self.employee_a_user, task.user_ids)

        transferred_session = self.env['project.task.work.session'].search([
            ('task_id', '=', task.id), ('employee_id', '=', self.employee_a.id),
        ])
        self.assertEqual(transferred_session.state, 'transferred')

        transfer_record = self.env['project.task.transfer'].search([('task_id', '=', task.id)])
        self.assertEqual(len(transfer_record), 1)
        self.assertFalse(transfer_record.reason)

    def test_transfer_with_reason_stores_it(self):
        task = self._create_task()
        wizard = self.env['project.task.transfer.wizard'].with_user(self.manager_user).create({
            'task_id': task.id,
            'from_employee_id': self.employee_a.id,
            'to_employee_id': self.employee_b.id,
            'reason': 'Employee is absent.',
        })
        wizard.action_transfer()
        transfer_record = self.env['project.task.transfer'].search([('task_id', '=', task.id)])
        self.assertEqual(transfer_record.reason, 'Employee is absent.')

    def test_transfer_does_not_affect_other_concurrent_employee(self):
        employee_c_user = self.env['res.users'].with_context(
            no_reset_password=True, mail_create_nolog=True,
            mail_create_nosubscribe=True, mail_notrack=True,
        ).create({
            'name': 'Employee C',
            'login': 'test_employee_c_ptsm',
            'email': 'employee_c_ptsm@example.com',
            'groups_id': [(6, 0, [self.env.ref('project.group_project_user').id])],
        })
        employee_c = self.env['hr.employee'].create({
            'name': 'Employee C', 'user_id': employee_c_user.id,
        })
        task = self._create_task(user_ids=[
            (6, 0, [self.employee_a_user.id, employee_c_user.id]),
        ])
        task.with_user(self.employee_a_user).action_start_work()
        task.with_user(employee_c_user).action_start_work()

        wizard = self.env['project.task.transfer.wizard'].with_user(self.manager_user).create({
            'task_id': task.id,
            'from_employee_id': self.employee_a.id,
            'to_employee_id': self.employee_b.id,
        })
        wizard.action_transfer()

        session_c = self.env['project.task.work.session'].search([
            ('task_id', '=', task.id), ('employee_id', '=', employee_c.id),
        ])
        self.assertEqual(session_c.state, 'running', "Bystander employee's session must be untouched.")

    def test_manager_cannot_transfer_unrelated_project_task(self):
        other_project = self.env['project.project'].create({
            'name': 'Unrelated Project PTSM',
            'partner_id': self.customer.id,
        })
        other_task = self.env['project.task'].sudo().create({
            'name': 'Unrelated Task',
            'project_id': other_project.id,
            'user_ids': [(6, 0, [self.employee_b_user.id])],
        })
        with self.assertRaises(UserError):
            other_task.with_user(self.manager_user).action_transfer_task()

    # -- BILLING ---------------------------------------------------

    def test_hourly_billing_amount(self):
        task = self._create_task(billing_mode='hourly', hourly_rate=300.0, is_billable=True)
        self._create_closed_session(task, self.employee_a, self.employee_a_user, hours=2.0)
        self.assertAlmostEqual(task.actual_work_hours, 2.0, places=4)
        self.assertAlmostEqual(task.billable_amount, 600.0, places=2)

    def test_per_task_billing_ignores_actual_hours(self):
        task = self._create_task(billing_mode='task', task_fixed_price=750.0, is_billable=True)
        self._create_closed_session(task, self.employee_a, self.employee_a_user, hours=3.0)
        self.assertAlmostEqual(task.actual_work_hours, 3.0, places=4)
        self.assertAlmostEqual(task.billable_amount, 750.0, places=2)

    def test_non_billable_amount_is_zero(self):
        task = self._create_task(billing_mode='hourly', hourly_rate=300.0, is_billable=False)
        self._create_closed_session(task, self.employee_a, self.employee_a_user, hours=2.0)
        self.assertEqual(task.billable_amount, 0.0)

    def test_billing_survives_transfer(self):
        task = self._create_task(billing_mode='hourly', hourly_rate=300.0)
        self._create_closed_session(task, self.employee_a, self.employee_a_user, hours=2.0)
        wizard = self.env['project.task.transfer.wizard'].with_user(self.manager_user).create({
            'task_id': task.id,
            'from_employee_id': self.employee_a.id,
            'to_employee_id': self.employee_b.id,
        })
        wizard.action_transfer()
        self._create_closed_session(task, self.employee_b, self.employee_b_user, hours=1.0)
        self.assertAlmostEqual(task.actual_work_hours, 3.0, places=4)
        self.assertAlmostEqual(task.billable_amount, 900.0, places=2)

    # -- ACTUAL TIME / VARIANCE / REMAINING / OVERRUN ------------------

    def test_variance_remaining_overrun_within_estimate(self):
        task = self._create_task(estimated_time=5.0)
        self._create_closed_session(task, self.employee_a, self.employee_a_user, hours=3.0)
        self.assertAlmostEqual(task.variance_to_finish, 2.0, places=4)
        self.assertAlmostEqual(task.remaining_estimated_hours, 2.0, places=4)
        self.assertAlmostEqual(task.overrun_hours, 0.0, places=4)

    def test_variance_remaining_overrun_over_estimate(self):
        task = self._create_task(estimated_time=5.0)
        self._create_closed_session(task, self.employee_a, self.employee_a_user, hours=6.0)
        self.assertAlmostEqual(task.variance_to_finish, -1.0, places=4)
        self.assertAlmostEqual(task.remaining_estimated_hours, 0.0, places=4)
        self.assertAlmostEqual(task.overrun_hours, 1.0, places=4)

    def test_actual_time_does_not_double_count_sessions(self):
        task = self._create_task()
        self._create_closed_session(task, self.employee_a, self.employee_a_user, hours=1.5)
        self._create_closed_session(task, self.employee_a, self.employee_a_user, hours=2.0)
        self.assertAlmostEqual(task.actual_work_hours, 3.5, places=4)

    # -- SECURITY-SENSITIVE OPERATIONS ------------------------------

    def test_employee_cannot_change_billing_fields(self):
        task = self._create_task()
        with self.assertRaises(UserError):
            task.with_user(self.employee_a_user).write({'hourly_rate': 500.0})

    def test_employee_cannot_change_estimated_time(self):
        task = self._create_task()
        with self.assertRaises(UserError):
            task.with_user(self.employee_a_user).write({'estimated_time': 10.0})

    def test_employee_cannot_approve_or_reject(self):
        task = self._create_task()
        task.with_user(self.employee_a_user).action_start_work()
        task.with_user(self.employee_a_user).action_pause_work()
        task.with_user(self.employee_a_user).write({'employee_remarks': 'Done.'})
        task.with_user(self.employee_a_user).action_submit_for_verification()
        # employee_b: not a manager and not the submitter either -
        # isolates the "not authorized" path from the separate
        # "cannot approve your own submission" rule.
        with self.assertRaises(UserError):
            task.with_user(self.employee_b_user).action_approve_task()
        with self.assertRaises(UserError):
            task.with_user(self.employee_b_user).action_reject_task()

    def test_employee_cannot_transfer(self):
        task = self._create_task()
        with self.assertRaises(UserError):
            task.with_user(self.employee_a_user).action_transfer_task()

    def test_employee_cannot_change_project_manager(self):
        with self.assertRaises(UserError):
            self.project.with_user(self.employee_a_user).write({
                'project_manager_id': self.employee_b.id,
            })

    def test_employee_cannot_modify_another_employees_work_session(self):
        task = self._create_task(user_ids=[
            (6, 0, [self.employee_a_user.id, self.employee_b_user.id]),
        ])
        task.with_user(self.employee_a_user).action_start_work()
        session_a = self.env['project.task.work.session'].search([
            ('task_id', '=', task.id), ('employee_id', '=', self.employee_a.id),
        ])
        with self.assertRaises(AccessError):
            session_a.with_user(self.employee_b_user).write({'pause_reason': 'not mine to edit'})

    def test_employee_cannot_delete_historical_work_session(self):
        task = self._create_task()
        self._create_closed_session(task, self.employee_a, self.employee_a_user, hours=1.0)
        session = self.env['project.task.work.session'].search([('task_id', '=', task.id)])
        with self.assertRaises((AccessError, UserError)):
            session.with_user(self.employee_a_user).unlink()
