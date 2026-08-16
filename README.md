# Odoo 18 Project Task Service Management

An Odoo 18 Community custom module for managing customer projects,
service tasks, employee work time, task verification, task transfers,
billing, notifications, and management reporting.

## Main Features

- Customer-based project management
- Multiple projects per customer
- Project Manager assignment
- Employee task assignment
- Multiple employees per task
- Automatic work-time tracking
- START / PAUSE / RESUME workflow
- Estimated vs Actual time
- Time variance and overrun calculation
- Employee remarks
- Employee DONE submission
- Manager verification
- Approve / Reject workflow
- Task transfer between employees
- Optional transfer reason
- Transfer history
- Employee-wise work-time tracking
- Hourly customer billing
- Per-task customer billing
- Manager dashboard
- Employee workload reporting
- Customer and project reporting
- Odoo notifications
- Role-based access control

## Business Workflow

Customer
↓
Project
↓
Project Manager
↓
Task
↓
Employee Assignment
↓
START
↓
PAUSE / RESUME
↓
Employee DONE
↓
Manager Verification
↓
APPROVE / REJECT
↓
Task Completion

If an employee becomes unavailable:

Employee A
↓
Manager transfers task
↓
Employee B
↓
Same task continues

## Time Tracking

Employees do not manually enter their working time.

The system records Work Sessions when an employee:

- Starts a task
- Pauses a task
- Resumes a task

Actual task time is calculated from the recorded Work Sessions.

### Example

Estimated Time:

5 hours

Actual Time:

3 hours

Variance:

+2 hours

If actual time exceeds the estimate:

Estimated Time:

5 hours

Actual Time:

6 hours

Variance:

-1 hour

## Task Transfer

A Project Manager can transfer a task from one employee to another.

The original task is retained.

Employee A's historical work time remains associated with Employee A.

Employee B can continue working on the same task.

Example:

Employee A: 2h 15m
Employee B: 1h 40m

Total Task Time: 3h 55m

Transfer reason is optional.

## Billing

Tasks can use two billing methods.

### Hourly Billing

Example:

Rate: ₹300/hour

Actual billable time: 4 hours

Billable amount:

₹1,200

### Per-Task Billing

Example:

Task price: ₹750

Actual employee time does not change the customer price.

Billable amount:

₹750

Time tracking and customer billing are treated separately.

## User Roles

### Administrator

Can configure the complete system and access all projects, tasks,
billing, reports, and settings.

### Project Manager

Can manage authorized projects, assign employees, transfer tasks,
verify completed work, approve/reject tasks, and view management
reports.

### Employee

Can work on assigned tasks using START, PAUSE, RESUME and DONE.

Employees cannot approve, reject, transfer tasks, or modify billing
configuration.

## Manager Dashboard

The dashboard provides visibility into:

- Active tasks
- Pending verification
- Completed tasks
- Estimated hours
- Actual hours
- Variance
- Overrun
- Employee workload
- Project performance
- Customer performance
- Billable amounts
- Task transfers
- Work sessions

## Requirements

- Odoo 18 Community Edition
- Project
- Employees
- Mail
- Timesheets, where applicable

## Installation

Copy the module into the Odoo custom addons directory.

Example:

`/mnt/extra-addons/`

Restart Odoo and update the Apps list.

Then install:

**Project Task Service Management**

## Development Status

This module is under active development and testing.

Features are being implemented and tested incrementally.

## License

Specify the appropriate license for your organization before
publishing the repository publicly.
