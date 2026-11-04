# Integration smoke test for works-core (ASCII only)
$ErrorActionPreference = 'Continue'
Set-Location 'D:\AI\AI-projects\works-core'

# 0) compile check (glob handles cyrillic filenames inside python)
python -X utf8 -c "import py_compile,glob; files=['server.py']+glob.glob('core/*.py')+glob.glob('modules/*/*.py'); [py_compile.compile(f,doraise=True) for f in files]; print('COMPILE OK', len(files))"
if ($LASTEXITCODE -ne 0) { Write-Output 'COMPILE FAIL'; exit 1 }

# 1) unit tests
python -X utf8 _grade_test.py
if ($LASTEXITCODE -ne 0) { Write-Output 'UNIT FAIL'; exit 1 }

if (Test-Path '_teststore') { Remove-Item -Recurse -Force '_teststore' }

$script:fail = 0
function Chk($name, $cond) { if ($cond) { Write-Output ("OK   " + $name) } else { Write-Output ("FAIL " + $name); $script:fail++ } }

$p = Start-Process -FilePath 'python' -ArgumentList '-X','utf8','server.py','--port','8099','--store','_teststore','--demo','--no-pass' -WorkingDirectory $PWD -WindowStyle Hidden -PassThru -RedirectStandardOutput "$PWD\_test_out.log" -RedirectStandardError "$PWD\_test_err.log"
Start-Sleep -Seconds 6

try {
  curl.exe -s -c "$PWD\_ck.txt" -d 'student=s1' -d 'next=/' 'http://localhost:8099/_login' | Out-Null
  curl.exe -s -c "$PWD\_staff.txt" -d 'pass=x' 'http://localhost:8099/_staff_login' | Out-Null

  # markdown rendered on student task page
  $t = curl.exe -s -b "$PWD\_ck.txt" 'http://localhost:8099/task/t1'
  Chk 'md h2 rendered' ($t -match '<h2>')
  Chk 'md strong rendered' ($t -match '<strong>')
  Chk 'md list rendered' ($t -match '<li>')
  Chk 'no raw md hashes' ($t -notmatch '<div class="task-desc">##')

  # set past deadline with EMPTY form_json -> form must survive
  curl.exe -s -b "$PWD\_staff.txt" -d 'title=' -d 'description=' -d 'form_json=' -d 'deadline=2020-01-01 09:00' 'http://localhost:8099/staff/edit_task/t1' | Out-Null
  $tp = curl.exe -s -b "$PWD\_staff.txt" 'http://localhost:8099/staff/task/t1'
  Chk 'staff sees deadline' ($tp -match '01\.01\.2020')
  Chk 'staff sees expired mark' ($tp -match 'state-')

  $t2 = curl.exe -s -b "$PWD\_ck.txt" 'http://localhost:8099/task/t1'
  Chk 'student sees deadline' ($t2 -match '01\.01\.2020')
  Chk 'form survived empty form_json' ($t2 -match 'name="width"')

  # submit after deadline -> late flag stored
  curl.exe -s -b "$PWD\_ck.txt" -F 'task=t1' -F 'width=24' -F 'length=18' -F 'height=4.2' -F 'detector_type=IP212' -F 'detectors_num=6' -F 'loops=2' -F 'justification=late-test' 'http://localhost:8099/api/submit' | Out-Null
  python -X utf8 _chk_late.py
  if ($LASTEXITCODE -eq 0) { Write-Output 'OK   late flag stored' } else { Write-Output 'FAIL late flag stored'; $script:fail++ }
  $sp = curl.exe -s -b "$PWD\_staff.txt" 'http://localhost:8099/staff/sub/t1__s1'
  Chk 'sub page shows versions' ($sp -match 'v1')

  # clear deadline
  curl.exe -s -b "$PWD\_staff.txt" -d 'title=' -d 'description=' -d 'form_json=' -d 'deadline=' 'http://localhost:8099/staff/edit_task/t1' | Out-Null
  $tp2 = curl.exe -s -b "$PWD\_staff.txt" 'http://localhost:8099/staff/task/t1'
  Chk 'deadline cleared' ($tp2 -notmatch '01\.01\.2020')

  # enrollment gate
  curl.exe -s -b "$PWD\_staff.txt" -d 'course=c1' -d 'student=s1' -d 'act=off' 'http://localhost:8099/staff/enroll' | Out-Null
  $g = curl.exe -s -b "$PWD\_ck.txt" 'http://localhost:8099/course/c1'
  Chk 'unenrolled blocked' ($g -notmatch 'lesson-list')
  curl.exe -s -b "$PWD\_staff.txt" -d 'course=c1' -d 'student=s1' -d 'act=on' 'http://localhost:8099/staff/enroll' | Out-Null
  $g2 = curl.exe -s -b "$PWD\_ck.txt" 'http://localhost:8099/course/c1'
  Chk 'reenrolled ok' ($g2 -match 'lesson-list')

  # board page
  $b = curl.exe -s -b "$PWD\_staff.txt" 'http://localhost:8099/board'
  Chk 'board renders' ($b -match 'pod-card')

  # CSV export
  curl.exe -s -o "$PWD\_exp.csv" -b "$PWD\_staff.txt" 'http://localhost:8099/staff/export/course/c1'
  python -X utf8 _chk_export.py
  if ($LASTEXITCODE -eq 0) { Write-Output 'OK   export csv' } else { Write-Output 'FAIL export csv'; $script:fail++ }

  # import group from txt (2 new, 2 duplicates skipped)
  $im = curl.exe -s -b "$PWD\_staff.txt" -F 'course=c1' -F 'group=' -F 'text=' -F 'file=@_group.txt' 'http://localhost:8099/staff/import_group'
  Chk 'import redirect report' ($im -match 'imp=2/2')
  python -X utf8 _chk_import.py
  if ($LASTEXITCODE -eq 0) { Write-Output 'OK   import group' } else { Write-Output 'FAIL import group'; $script:fail++ }

  # new imported student can log in (s7 = Novikov)
  $s7 = curl.exe -s -i -d 'student=s7' 'http://localhost:8099/_login'
  Chk 'imported student login' ($s7 -match 'Set-Cookie')

  # ---- brigades: one report for the whole team ----
  $imb = curl.exe -s -b "$PWD\_staff.txt" -F 'course=c1' -F 'group=' -F 'text=' -F 'file=@_brig.txt' 'http://localhost:8099/staff/import_group'
  Chk 'brigade import redirect' ($imb -match 'imp=2/0')
  python -X utf8 _chk_brig.py
  if ($LASTEXITCODE -eq 0) { Write-Output 'OK   brigade field imported' } else { Write-Output 'FAIL brigade field imported'; $script:fail++ }

  curl.exe -s -b "$PWD\_staff.txt" -d 'course=c1' 'http://localhost:8099/staff/enroll_all' | Out-Null
  $cp = curl.exe -s -b "$PWD\_staff.txt" 'http://localhost:8099/staff/course/c1'
  Chk 'staff table shows brigade badge' ($cp -match 'team-badge')

  $p1b = curl.exe -s -b "$PWD\_ck.txt" 'http://localhost:8099/task/t1'
  Chk 'no brigade select for solo student' ($p1b -notmatch 'name="brigade"')
  curl.exe -s -c "$PWD\_ck9.txt" -d 'student=s9' -d 'next=/' 'http://localhost:8099/_login' | Out-Null
  $p9 = curl.exe -s -b "$PWD\_ck9.txt" 'http://localhost:8099/task/t1'
  Chk 'brigade select shown for member' ($p9 -match 'name="brigade"')

  curl.exe -s -b "$PWD\_ck9.txt" -F 'task=t1' -F 'brigade=BR-1' -F 'width=10' -F 'length=10' -F 'height=2' -F 'detector_type=IP212' -F 'detectors_num=4' -F 'loops=1' -F 'justification=brigade-report' 'http://localhost:8099/api/submit' | Out-Null
  python -X utf8 _chk_brig2.py
  if ($LASTEXITCODE -eq 0) { Write-Output 'OK   brigade participants' } else { Write-Output 'FAIL brigade participants'; $script:fail++ }

  $b2 = curl.exe -s -b "$PWD\_staff.txt" 'http://localhost:8099/board'
  Chk 'board shows brigade team' ($b2 -match 'BR-1')

  # ---- dark theme toggle ----
  $lp = curl.exe -s 'http://localhost:8099/_login'
  Chk 'theme toggle in topbar' ($lp -match 'theme-toggle')
  $r0 = curl.exe -s -i 'http://localhost:8099/'
  Chk 'root redirects to _login' ($r0 -match 'Location: /_login')

  # ---- course access by group ----
  curl.exe -s -b "$PWD\_staff.txt" -d 'title=GRP-ONLY-COURSE' 'http://localhost:8099/staff/new_course' | Out-Null
  curl.exe -s -b "$PWD\_staff.txt" -d 'course=c2' -d 'group=P-22' -d 'act=add' 'http://localhost:8099/staff/course_group' | Out-Null
  curl.exe -s -c "$PWD\_ck7.txt" -d 'student=s7' -d 'next=/' 'http://localhost:8099/_login' | Out-Null
  $h7 = curl.exe -s -b "$PWD\_ck7.txt" 'http://localhost:8099/'
  Chk 'group member sees group course' ($h7 -match 'GRP-ONLY-COURSE')
  $h1 = curl.exe -s -b "$PWD\_ck.txt" 'http://localhost:8099/'
  Chk 'other group does not see it' ($h1 -notmatch 'GRP-ONLY-COURSE')
  $g1 = curl.exe -s -b "$PWD\_ck.txt" 'http://localhost:8099/course/c2'
  Chk 'gate blocks other group' ($g1 -notmatch 'GRP-ONLY-COURSE')
  $g7 = curl.exe -s -b "$PWD\_ck7.txt" 'http://localhost:8099/course/c2'
  Chk 'gate allows own group' ($g7 -match 'GRP-ONLY-COURSE')
  curl.exe -s -b "$PWD\_staff.txt" -d 'course=c2' -d 'group=X-99' -d 'act=add' 'http://localhost:8099/staff/course_group' | Out-Null
  curl.exe -s -b "$PWD\_staff.txt" -d 'course=c2' -d 'group=P-22' -d 'act=off' 'http://localhost:8099/staff/course_group' | Out-Null
  $h7b = curl.exe -s -b "$PWD\_ck7.txt" 'http://localhost:8099/'
  Chk 'removed group loses access' ($h7b -notmatch 'GRP-ONLY-COURSE')
  $sp = curl.exe -s -b "$PWD\_staff.txt" 'http://localhost:8099/staff'
  Chk 'staff import card present' ($sp -match '/staff/import_group')

  # ---- self-service brigades (students name them, max by teacher) ----
  curl.exe -s -b "$PWD\_staff.txt" -d 'course=c1' -d 'max=1' 'http://localhost:8099/staff/brigade_max' | Out-Null
  curl.exe -s -b "$PWD\_ck.txt" -d 'course=c1' -d 'act=create' -d 'name=TEST-TEAM' 'http://localhost:8099/brigade' | Out-Null
  python -X utf8 _chk_brig3.py
  if ($LASTEXITCODE -eq 0) { Write-Output 'OK   brigade created by student' } else { Write-Output 'FAIL brigade created by student'; $script:fail++ }
  curl.exe -s -c "$PWD\_ck2.txt" -d 'student=s2' -d 'next=/' 'http://localhost:8099/_login' | Out-Null
  curl.exe -s -b "$PWD\_ck2.txt" -d 'course=c1' -d 'act=join' -d 'name=TEST-TEAM' 'http://localhost:8099/brigade' | Out-Null
  python -X utf8 _chk_brig4.py
  if ($LASTEXITCODE -eq 0) { Write-Output 'OK   brigade max enforced' } else { Write-Output 'FAIL brigade max enforced'; $script:fail++ }
  curl.exe -s -b "$PWD\_staff.txt" -d 'course=c1' -d 'max=5' 'http://localhost:8099/staff/brigade_max' | Out-Null
  curl.exe -s -b "$PWD\_ck2.txt" -d 'course=c1' -d 'act=join' -d 'name=TEST-TEAM' 'http://localhost:8099/brigade' | Out-Null
  python -X utf8 _chk_brig5.py
  if ($LASTEXITCODE -eq 0) { Write-Output 'OK   joined after max raised' } else { Write-Output 'FAIL joined after max raised'; $script:fail++ }
  $cp2 = curl.exe -s -b "$PWD\_ck.txt" 'http://localhost:8099/course/c1'
  Chk 'brigade box on course page' ($cp2 -match 'value="create"')

  # ---- scenarios module ----
  $scp = curl.exe -s -b "$PWD\_staff.txt" 'http://localhost:8099/staff/scenarios'
  Chk 'scenarios page lists kits' ($scp -match 'scenarios/import')
  curl.exe -s -b "$PWD\_staff.txt" -H 'Content-Type: application/json' -d '@_scn.json' 'http://localhost:8099/staff/scenarios/import' | Out-Null
  python -X utf8 _chk_scn.py
  if ($LASTEXITCODE -eq 0) { Write-Output 'OK   scenario import' } else { Write-Output 'FAIL scenario import'; $script:fail++ }
  $h1b = curl.exe -s -b "$PWD\_ck.txt" 'http://localhost:8099/course/c1'
  Chk 'scenario lesson visible' ($h1b -match 'SCN-TEST')
  $h1b | Out-File -Encoding utf8 "$PWD\_tmp_page.html"
  python -X utf8 _chk_nomat.py
  if ($LASTEXITCODE -eq 0) { Write-Output 'OK   materials hidden from students' } else { Write-Output 'FAIL materials hidden from students'; $script:fail++ }

  # ---- interactive plan widget (fake kit with files) ----
  python -X utf8 _mk_kit.py make | Out-Null
  curl.exe -s -b "$PWD\_staff.txt" -H 'Content-Type: application/json' -d '@_smoke_kit.json' 'http://localhost:8099/staff/scenarios/import' | Out-Null
  $scnOut = (python -X utf8 _chk_scn2.py)
  $scnTid = ($scnOut -split '\s+')[0]
  $scnLid = ($scnOut -split '\s+')[1]
  if ($LASTEXITCODE -ne 0) { Write-Output 'FAIL scenario kit files'; $script:fail++ } else { Write-Output 'OK   scenario kit files (mats 02/05/06, plans stripped)' }
  $tp0 = curl.exe -s -b "$PWD\_ck.txt" "http://localhost:8099/task/$scnTid"
  Chk 'scenario task waits for issue' ($tp0 -notmatch 'task-form')
  curl.exe -s -b "$PWD\_staff.txt" -d "task=$scnTid" -d 'all=on' 'http://localhost:8099/staff/task_issue' | Out-Null
  $tp3 = curl.exe -s -b "$PWD\_ck.txt" "http://localhost:8099/task/$scnTid"
  Chk 'issue-all makes task visible' ($tp3 -match 'task-form')
  Chk 'scenario task has plan widget' ($tp3 -match 'src="/plan/')
  $pp = curl.exe -s -b "$PWD\_ck.txt" "http://localhost:8099/plan/$scnTid"
  Chk 'plan widget renders' ($pp -match 'wcplan_' -and $pp -match 'SK-1')
  curl.exe -s -b "$PWD\_ck.txt" -F "task=$scnTid" -F 'calc=test calc' -F 'plan_data=<_plan_data.json' 'http://localhost:8099/api/submit' | Out-Null
  $env:PLANKEY = "$scnTid" + '__s1'
  python -X utf8 _chk_subplan.py
  if ($LASTEXITCODE -eq 0) { Write-Output 'OK   plan data stored with report' } else { Write-Output 'FAIL plan data stored with report'; $script:fail++ }
  $sp3 = curl.exe -s -b "$PWD\_staff.txt" "http://localhost:8099/staff/sub/${scnTid}__s1"
  Chk 'sub page links to plan view' ($sp3 -match '/plan/')
  $pv = curl.exe -s -b "$PWD\_staff.txt" "http://localhost:8099/plan/${scnTid}?sub=${scnTid}__s1&v=1"
  Chk 'teacher sees student plan (read-only)' ($pv -match 'RO=true')

  # ---- issue scenario to brigades ----
  curl.exe -s -b "$PWD\_staff.txt" -d "task=$scnTid" -d 'brigade=TEST-TEAM' 'http://localhost:8099/staff/task_issue' | Out-Null
  $t1i = curl.exe -s -b "$PWD\_ck.txt" "http://localhost:8099/task/$scnTid"
  Chk 'issued brigade sees task' ($t1i -match 'task-form')
  $t9i = curl.exe -s -b "$PWD\_ck9.txt" "http://localhost:8099/task/$scnTid"
  Chk 'other brigade blocked' ($t9i -notmatch 'task-form')
  $li = curl.exe -s -b "$PWD\_ck9.txt" "http://localhost:8099/lesson/$scnLid"
  Chk 'lesson list hides issued task' ($li -notmatch 'href="/task/')
  $r403 = curl.exe -s -i -b "$PWD\_ck9.txt" -F "task=$scnTid" -F 'calc=x' 'http://localhost:8099/api/submit'
  Chk 'submit blocked for other brigade' ($r403 -match '403')
  $pv9 = curl.exe -s -b "$PWD\_ck9.txt" "http://localhost:8099/plan/$scnTid"
  Chk 'plan view blocked for other brigade' ($pv9 -notmatch 'wcplan_')
  $st2 = curl.exe -s -b "$PWD\_staff.txt" "http://localhost:8099/staff/task/$scnTid"
  Chk 'staff issue card present' ($st2 -match 'task_issue')
  $rp = curl.exe -s -b "$PWD\_staff.txt" "http://localhost:8099/staff/scenarios"
  Chk 'repair button shown' ($rp -match 'scenarios/repair')
  $rr = curl.exe -s -b "$PWD\_staff.txt" -d "course=c1" -d 'kit=_smoketest_kit' 'http://localhost:8099/staff/scenarios/repair'
  Chk 'repair runs' ($rr -match 'ok:')
  $sp4 = curl.exe -s -b "$PWD\_ck.txt" "http://localhost:8099/task/$scnTid"
  Chk 'repair keeps form intact' ($sp4 -match 'name="plan_data"')
  curl.exe -s -b "$PWD\_staff.txt" -d "task=$scnTid" -d 'all=on' 'http://localhost:8099/staff/task_issue' | Out-Null
  $t9b = curl.exe -s -b "$PWD\_ck9.txt" "http://localhost:8099/task/$scnTid"
  Chk 'issue-all restores visibility' ($t9b -match 'task-form')
  python -X utf8 _mk_kit.py remove | Out-Null

} finally {
  Stop-Process -Id $p.Id -Force -ErrorAction SilentlyContinue
}

# ---- password change flow (separate instance with --pass) ----
if (Test-Path '_passstore') { Remove-Item -Recurse -Force '_passstore' }
$p2 = Start-Process -FilePath 'python' -ArgumentList '-X','utf8','server.py','--port','8098','--store','_passstore','--demo','--pass','TESTPW' -WorkingDirectory $PWD -WindowStyle Hidden -PassThru -RedirectStandardOutput "$PWD\_test_out2.log" -RedirectStandardError "$PWD\_test_err2.log"
Start-Sleep -Seconds 6
$p3 = $null
try {
  $s1 = curl.exe -s -i -c "$PWD\_pw.txt" -d 'pass=TESTPW' 'http://localhost:8098/_staff_login'
  Chk 'login with initial password' ($s1 -match 'Set-Cookie')

  $s0 = curl.exe -s -i -b "$PWD\_pw.txt" -d 'old=WRONG' -d 'new=zz' -d 'new2=zz' 'http://localhost:8098/staff/password'
  Chk 'wrong old password rejected' ($s0 -match 'err=old')

  curl.exe -s -b "$PWD\_pw.txt" -d 'old=TESTPW' -d 'new=NEWPW99' -d 'new2=NEWPW99' 'http://localhost:8098/staff/password' | Out-Null
  Stop-Process -Id $p2.Id -Force -ErrorAction SilentlyContinue
  Start-Sleep -Seconds 2

  # restart WITHOUT --pass: saved hash must be used
  $p3 = Start-Process -FilePath 'python' -ArgumentList '-X','utf8','server.py','--port','8098','--store','_passstore' -WorkingDirectory $PWD -WindowStyle Hidden -PassThru -RedirectStandardOutput "$PWD\_test_out2.log" -RedirectStandardError "$PWD\_test_err2.log"
  Start-Sleep -Seconds 6
  $s2 = curl.exe -s -i -c "$PWD\_pw2.txt" -d 'pass=NEWPW99' 'http://localhost:8098/_staff_login'
  Chk 'changed password works after restart' ($s2 -match 'Set-Cookie')
  $s3 = curl.exe -s -i -d 'pass=TESTPW' 'http://localhost:8098/_staff_login'
  Chk 'old password rejected' ($s3 -notmatch 'Set-Cookie')
  $s4 = curl.exe -s -b "$PWD\_pw2.txt" 'http://localhost:8098/staff/password'
  Chk 'password page renders' ($s4 -match 'staff-card')

} finally {
  if ($p3) { Stop-Process -Id $p3.Id -Force -ErrorAction SilentlyContinue }
}

if ($script:fail -eq 0) { Write-Output 'ALL TESTS PASSED' } else { Write-Output ("FAILED: " + $script:fail); Get-Content "$PWD\_test_err.log" -ErrorAction SilentlyContinue | Select-Object -Last 10; Get-Content "$PWD\_test_err2.log" -ErrorAction SilentlyContinue | Select-Object -Last 10 }
