const $ = s => document.querySelector(s);
const $$ = s => [...document.querySelectorAll(s)];
let employees = [], schedule = [], currentUser = null;
let currentDepartment = localStorage.getItem('escalaDepartment') || 'SAC_ECOMMERCE';

const departmentName = () => currentDepartment === 'TELE_VENDAS' ? 'Televendas' : 'Atendimento';
const can = key => !!currentUser && (currentUser.role === 'ADMIN' || !!currentUser[key]);
const scoped = url => url + (url.includes('?') ? '&' : '?') + 'department=' + encodeURIComponent(currentDepartment);
const iso = d => new Date(d).toISOString().slice(0, 10);
const br = d => new Date(d + 'T12:00:00').toLocaleDateString('pt-BR', {day:'2-digit', month:'short'});
const full = d => new Date(d + 'T12:00:00').toLocaleDateString('pt-BR', {weekday:'long', day:'2-digit', month:'long', year:'numeric'});

async function api(url, options = {}) {
  const token = localStorage.getItem('escalaSessionToken');
  const headers = {'Content-Type':'application/json', ...(token ? {'Authorization':'Bearer ' + token} : {}), ...(options.headers || {})};
  const response = await fetch(url, {...options, headers});
  const data = await response.json();
  if (!response.ok) throw new Error(data.error || 'Erro inesperado');
  return data;
}

function toast(text) {
  $('#toast').textContent = text;
  $('#toast').classList.add('show');
  clearTimeout(toast.timer);
  toast.timer = setTimeout(() => $('#toast').classList.remove('show'), 2500);
}

function defaults() {
  const today = new Date();
  $('#today').textContent = today.toLocaleDateString('pt-BR', {weekday:'long', day:'2-digit', month:'long'}).replace(/^./, c => c.toUpperCase());
  $('#viewStart').value = iso(new Date(today.getFullYear(), today.getMonth(), 1));
  $('#viewEnd').value = iso(new Date(today.getFullYear(), today.getMonth() + 1, 0));
  const nextMonday = new Date(today);
  nextMonday.setDate(today.getDate() + ((8 - today.getDay()) % 7));
  $('#genStart').value = iso(nextMonday);
  $('#genEnd').value = iso(new Date(nextMonday.getFullYear(), nextMonday.getMonth() + 2, 0));
}

function applyDepartment() {
  document.body.classList.toggle('dept-tele', currentDepartment === 'TELE_VENDAS');
  document.body.classList.toggle('dept-sac', currentDepartment !== 'TELE_VENDAS');
  const el = $('#currentDepartment');
  if (el) el.textContent = departmentName();
  const target = $('#switchTarget');
  if (target) target.textContent = currentDepartment === 'TELE_VENDAS' ? 'Ir para Atendimento' : 'Ir para Televendas';
  localStorage.setItem('escalaDepartment', currentDepartment);
}

function setupHeaderTools() {
  document.title = 'Sistema de Escalas';
  $('.brand b').textContent = 'Escalas';
  $('.brand small').textContent = 'Gestão de setores';
  const tools = document.createElement('div');
  tools.className = 'headerTools';
  tools.innerHTML = `<div class="sectorControl"><span>Setor atual</span><strong id="currentDepartment">Atendimento</strong></div>
    <button id="departmentSwitch" class="sectorSwitch">⇄ <span id="switchTarget">Ir para Televendas</span></button>
    <small id="networkAddress">Rede local</small>`;
  document.querySelector('header').appendChild(tools);
  $('#departmentSwitch').onclick = async () => {
    if (!can('can_switch_departments')) return;
    currentDepartment = currentDepartment === 'TELE_VENDAS' ? 'SAC_ECOMMERCE' : 'TELE_VENDAS';
    applyDepartment();
    await loadAll();
  };
  applyDepartment();
  api('/api/server-info').then(d => $('#networkAddress').textContent = 'Rede: ' + (d.urls[0] || location.origin)).catch(() => {});
}

function applyPermissions() {
  const admin = currentUser.role === 'ADMIN';
  $$('.adminOnly').forEach(el => el.classList.toggle('hidden', !admin));
  $('#openGenerator').classList.toggle('hidden', !can('can_generate_schedule'));
  $('#emptyGenerate').classList.toggle('hidden', !can('can_generate_schedule'));
  $('#manageTeamFromSchedule').classList.toggle('hidden', !can('can_manage_employees'));
  $('#addEmployee').classList.toggle('hidden', !can('can_manage_employees'));
  $('#openDutySwap').classList.add('hidden');
  $('.nav[data-page="central"]').classList.toggle('hidden', !can('can_manage_employees'));
  $('.nav[data-page="users"]').classList.toggle('hidden', !can('can_manage_users'));
  $('.nav[data-page="audit"]').classList.toggle('hidden', !can('can_manage_users'));
  $('.nav[data-page="backups"]').classList.toggle('hidden', !admin);
  $('#departmentSwitch').disabled = !can('can_switch_departments');
}

async function checkAuth() {
  const me = await api('/api/me');
  if (!me.authenticated) {
    $('#loginScreen').classList.remove('hidden');
    return;
  }
  currentUser = me.user;
  if (!can('can_switch_departments')) currentDepartment = currentUser.department || 'SAC_ECOMMERCE';
  $('#loginScreen').classList.add('hidden');
  $('#signedUser').textContent = currentUser.username;
  applyDepartment();
  applyPermissions();
  await loadAll();
}

async function loadAll() {
  employees = await api(scoped('/api/employees'));
  await Promise.all([loadSchedule(), loadDashboard()]);
  renderTeam();
  fillFirst();
  $('#pageSub').textContent = departmentName() + ' · rodízio e controle diário';
}

async function loadDashboard() {
  const d = await api(scoped('/api/dashboard'));
  $('#mActive').textContent = d.active;
  $('#mTeamDetail').textContent = `${d.n2} N2 · ${d.active - d.n2} equipe geral`;
  $('#mChanges').textContent = d.changes;
  $('#mNext').textContent = d.next_weekend?.name || '—';
  $('#mNextDate').textContent = d.next_weekend ? `${br(d.next_weekend.work_date)} · ${d.next_weekend.shift}` : 'escala não gerada';
}

async function loadSchedule() {
  const start = $('#viewStart').value, end = $('#viewEnd').value;
  schedule = await api(scoped(`/api/schedule?start=${start}&end=${end}`));
  renderSchedule(start, end);
}

function datesBetween(start, end) {
  const out = [], cursor = new Date(start + 'T12:00:00'), limit = new Date(end + 'T12:00:00');
  while (cursor <= limit) {
    out.push(iso(cursor));
    cursor.setDate(cursor.getDate() + 1);
  }
  return out;
}

function renderSchedule(start, end) {
  const dates = datesBetween(start, end);
  const map = new Map(schedule.map(x => [x.employee_id + '|' + x.work_date, x]));
  const heads = dates.map(d => {
    const dt = new Date(d + 'T12:00:00'), weekend = [0,6].includes(dt.getDay());
    return `<th class="${weekend ? 'weekend' : ''}">${dt.toLocaleDateString('pt-BR',{weekday:'short'}).replace('.','')}<br>${String(dt.getDate()).padStart(2,'0')}/${String(dt.getMonth()+1).padStart(2,'0')}</th>`;
  }).join('');

  const body = employees.filter(e => e.active).map(e => `<tr>
    <td class="person"><b>${e.name} <em class="group ${e.group_type}">${e.group_type}</em></b><small>${e.weekday_shift}</small></td>
    ${dates.map(d => {
      const x = map.get(e.id + '|' + d), weekend = [0,6].includes(new Date(d + 'T12:00:00').getDay());
      return `<td class="cell ${can('can_edit_schedule') ? 'editable' : ''} ${weekend ? 'weekend' : ''} ${x ? 'status-' + x.status : ''} ${x?.source === 'manual' ? 'source-manual' : ''}" data-e="${e.id}" data-d="${d}">${x ? `<span class="pill ${x.status}" title="${x.note || x.shift || ''}">${x.status === 'FERIAS' ? 'Férias' : x.status === 'AFASTADO' ? 'Afast.' : x.status}</span>` : '—'}</td>`;
    }).join('')}</tr>`).join('');

  $('#scheduleTable').innerHTML = `<thead><tr><th class="person">Colaborador</th>${heads}</tr></thead><tbody>${body}</tbody>`;
  $('#emptySchedule').classList.toggle('hidden', schedule.length > 0);
  $('#scheduleTable').classList.toggle('hidden', schedule.length === 0);
  if (can('can_edit_schedule')) $$('.cell.editable').forEach(cell => cell.onclick = () => openEdit(+cell.dataset.e, cell.dataset.d, map.get(cell.dataset.e + '|' + cell.dataset.d)));
}

function renderTeam() {
  $('#teamCards').innerHTML = employees.map(e => `<div class="empCard ${e.active ? '' : 'inactive'}">
    <span class="avatar">${e.name.split(' ').map(x=>x[0]).slice(0,2).join('')}</span>
    <div><b>${e.name} <em class="group ${e.group_type}">${e.group_type}</em></b><small>${e.active ? 'Participa da escala' : 'Fora da escala'}</small></div>
    <div class="shift"><small>Segunda a sexta</small><b>${e.weekday_shift}</b></div>
    <div class="shift"><small>Fim de semana</small><b>${e.weekend_shift}</b></div>
    <span class="order">#${e.rotation_order + 1}</span>
  </div>`).join('');
}

function fillFirst() {
  $('#genFirst').innerHTML = employees.filter(e => e.active && e.group_type === 'N2').map(e => `<option value="${e.id}">${e.name}</option>`).join('');
}

function openEdit(id, day, entry) {
  const employee = employees.find(e => e.id === id);
  $('#editEmployee').value = id;
  $('#editDay').value = day;
  $('#editTitle').textContent = employee.name;
  $('#editDate').textContent = full(day);
  $('#editStatus').value = entry?.status || 'T';
  $('#editShift').value = entry?.shift || employee.weekday_shift;
  $('#editNote').value = entry?.note || '';
  $('#editor').showModal();
}

async function saveEdit() {
  try {
    await api(scoped('/api/schedule/edit'), {method:'POST', body:JSON.stringify({
      employeeId:+$('#editEmployee').value,
      date:$('#editDay').value,
      status:$('#editStatus').value,
      shift:$('#editShift').value,
      note:$('#editNote').value
    })});
    $('#editor').close();
    toast('Alteração salva');
    await loadAll();
  } catch (error) { alert(error.message); }
}

async function generate() {
  const start = $('#genStart').value, end = $('#genEnd').value;
  if (!start || !end) return alert('Informe o período.');
  try {
    $('#generateBtn').disabled = true;
    $('#generateBtn').textContent = 'Gerando…';
    await api(scoped('/api/schedule/generate'), {method:'POST', body:JSON.stringify({start,end})});
    $('#generator').close();
    $('#viewStart').value = start;
    $('#viewEnd').value = end;
    toast('Escala gerada e validada');
    await loadAll();
  } catch (error) { alert(error.message); }
  finally { $('#generateBtn').disabled = false; $('#generateBtn').textContent = 'Atualizar escala'; }
}

async function addEmployee() {
  try {
    await api(scoped('/api/employees'), {method:'POST', body:JSON.stringify({
      name:$('#newName').value,
      groupType:$('#newGroup').value,
      weekdayShift:$('#newWeek').value,
      weekendShift:$('#newWeekend').value,
      rotationOrder:+$('#newOrder').value || 0
    })});
    $('#employeeDialog').close();
    toast('Colaborador adicionado');
    await loadAll();
  } catch (error) { alert(error.message); }
}

async function loadAudit() {
  try {
    const list = await api('/api/audit');
    $('#auditList').innerHTML = list.length ? list.map(x => {
      let details = {};
      try { details = JSON.parse(x.details); } catch {}
      return `<div class="auditItem"><div><b>${x.action} · ${x.entity}</b><small>${new Date(x.occurred_at).toLocaleString('pt-BR')} por ${x.user_name}</small><small>${details.employee || details.start || details.file || ''}</small></div><span class="tag">#${x.id}</span></div>`;
    }).join('') : '<div class="empty"><h3>Nenhuma alteração registrada</h3></div>';
  } catch (error) { toast(error.message); }
}

async function loadBackups() {
  try {
    const list = await api('/api/backups');
    $('#backupList').innerHTML = list.length ? list.map(x => `<div class="backupItem"><div><b>${x.name}</b><small>${new Date(x.modified).toLocaleString('pt-BR')} · ${(x.size/1024).toFixed(1)} KB</small></div></div>`).join('') : '<div class="empty"><h3>Nenhum backup criado</h3></div>';
  } catch (error) { toast(error.message); }
}

async function loadUsers() {
  try {
    const list = await api('/api/users');
    $('#userList').innerHTML = list.map(x => `<div class="userItem"><div><b>${x.name || x.username}</b><small>@${x.username} · ${x.role}</small></div><div><small>${x.email || 'sem e-mail'}</small></div><span class="tag">${x.active ? 'Ativo' : 'Inativo'}</span></div>`).join('');
  } catch (error) { toast(error.message); }
}

function setupNavigation() {
  const titles = {schedule:['Escala de trabalho','Rodízio N2 e controle diário'],team:['Equipe','Colaboradores e horários'],central:['Central','Integração opcional omitida da edição pública'],users:['Usuários','Acessos e perfis'],audit:['Auditoria','Histórico de mudanças'],backups:['Backups','Cópias locais do banco'],update:['Atualizar','Atualizador privado omitido da edição pública']};
  $$('.nav').forEach(btn => btn.onclick = async () => {
    const page = btn.dataset.page;
    $$('.nav').forEach(x => x.classList.toggle('active', x === btn));
    $$('.page').forEach(x => x.classList.toggle('active', x.id === page));
    $('#pageTitle').textContent = titles[page][0];
    $('#pageSub').textContent = titles[page][1];
    if (page === 'audit') await loadAudit();
    if (page === 'backups') await loadBackups();
    if (page === 'users') await loadUsers();
    if (page === 'central') {
      $('#centralConnection').textContent = 'Portfolio edition';
      $('#centralConnection').classList.add('ok');
      $('#centralPeople').innerHTML = '<div class="centralPerson"><b>Integração externa não publicada</b><small>O projeto original possuía sincronização opcional somente-leitura com outro SQLite. Caminhos e detalhes privados foram removidos.</small></div>';
      $('#syncCentral').disabled = true;
    }
    if (page === 'update') {
      $('#applyUpdate').disabled = true;
      $('.updatePanel .notice').textContent = 'A arquitetura de atualização existia no sistema operacional; o instalador privado foi removido desta edição pública.';
    }
  });
}

function setupActions() {
  $('#loginForm').onsubmit = async event => {
    event.preventDefault();
    $('#loginError').textContent = '';
    try {
      const login = await api('/api/login', {method:'POST', body:JSON.stringify({username:$('#loginUser').value,password:$('#loginPassword').value})});
      localStorage.setItem('escalaSessionToken', login.token);
      await checkAuth();
    } catch (error) { $('#loginError').textContent = error.message; }
  };
  $('#forgotPassword').onclick = () => alert('Na edição de portfólio, redefina o banco local ou crie outro usuário administrador. O envio de recuperação por e-mail foi removido.');
  $('#logoutBtn').onclick = async () => { try { await api('/api/logout',{method:'POST',body:'{}'}); } finally { localStorage.removeItem('escalaSessionToken'); location.reload(); } };
  $('#loadBtn').onclick = loadSchedule;
  $('#openGenerator').onclick = () => $('#generator').showModal();
  $('#emptyGenerate').onclick = () => $('#generator').showModal();
  $('#generateBtn').onclick = generate;
  $('#saveEdit').onclick = saveEdit;
  $('#addEmployee').onclick = () => { $('#employeeDialogTitle').textContent = 'Novo colaborador'; $('#newName').value=''; $('#employeeDialog').showModal(); };
  $('#manageTeamFromSchedule').onclick = () => $('#addEmployee').click();
  $('#saveEmployee').onclick = addEmployee;
  $('#refreshAudit').onclick = loadAudit;
  $('#createBackup').onclick = async () => { try { await api('/api/backup',{method:'POST',body:'{}'}); toast('Backup criado'); loadBackups(); } catch(e) { alert(e.message); } };
  $('#exportBtn').onclick = () => {
    const token = localStorage.getItem('escalaSessionToken');
    const url = scoped(`/api/export.csv?start=${$('#viewStart').value}&end=${$('#viewEnd').value}`);
    fetch(url,{headers:{Authorization:'Bearer '+token}}).then(r => r.blob()).then(blob => {
      const a=document.createElement('a'); a.href=URL.createObjectURL(blob); a.download='escala.csv'; a.click(); URL.revokeObjectURL(a.href);
    });
  };
  $('#addUser').onclick = () => { $('#accessUsername').value=''; $('#accessEmail').value=''; $('#userDialog').showModal(); };
  $('#saveUser').onclick = async () => {
    const password = prompt('Defina uma senha temporária de ao menos 8 caracteres para o usuário:');
    if (!password) return;
    try {
      await api('/api/users/create',{method:'POST',body:JSON.stringify({username:$('#accessUsername').value,email:$('#accessEmail').value,role:$('#accessRole').value,password})});
      $('#userDialog').close(); toast('Usuário criado'); loadUsers();
    } catch(e) { alert(e.message); }
  };
  $('#changeAdminPassword').onclick = () => alert('Para a Portfolio Edition, altere ESCALA_ADMIN_PASSWORD antes de criar um banco novo.');
  $('#openDutySwap').onclick = () => alert('O fluxo completo de troca de plantonista permanece documentado, mas foi removido do demo público para manter a edição enxuta.');
}

setupHeaderTools();
setupNavigation();
setupActions();
defaults();
checkAuth().catch(error => alert('Não foi possível iniciar o sistema: ' + error.message));
