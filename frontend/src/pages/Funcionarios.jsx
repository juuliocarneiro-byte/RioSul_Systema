import React, { useEffect, useState } from "react";
import api from "@/lib/api";
import { Plus, Edit, Trash2 } from "lucide-react";
import { toast } from "sonner";

export default function Funcionarios() {
  const [list, setList] = useState([]);
  const [form, setForm] = useState({ login: "", password: "", name: "", role: "vendedor", active: true });
  const [confirmDel, setConfirmDel] = useState(null);
  const load = () => api.get("/users").then(r => setList(r.data));
  useEffect(() => { load(); }, []);
  const save = async () => {
    try {
      if (form.id) { const upd = { login: form.login, name: form.name, role: form.role, active: form.active }; if (form.password) upd.password = form.password; await api.put(`/users/${form.id}`, upd); }
      else await api.post("/users", form);
      setForm({ login: "", password: "", name: "", role: "vendedor", active: true }); load(); toast.success("Salvo");
    } catch (e) { toast.error(e.response?.data?.detail || "Erro"); }
  };
  const removeUser = async () => {
    if (!confirmDel) return;
    try {
      const { data } = await api.delete(`/users/${confirmDel.id}/hard`);
      toast.success(`${confirmDel.name} excluído com ${data.deleted_sales} venda(s) e ${data.deleted_vales} vale(s)`);
      setConfirmDel(null);
      setForm({ login: "", password: "", name: "", role: "vendedor", active: true });
      load();
    } catch (e) { toast.error(e.response?.data?.detail || "Erro ao excluir funcionário"); }
  };
  return (
    <div className="space-y-4">
      <h1 className="text-2xl font-bold text-white">Funcionários</h1>
      <div className="grid md:grid-cols-3 gap-4">
        <div className="card-riosul p-4 space-y-2">
          <input value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} placeholder="Nome" className="w-full bg-zinc-900 border border-zinc-800 rounded px-3 py-2 text-white text-sm" data-testid="user-name" />
          <input value={form.login} onChange={(e) => setForm({ ...form, login: e.target.value })} placeholder="Login" disabled={!!form.id} className="w-full bg-zinc-900 border border-zinc-800 rounded px-3 py-2 text-white text-sm" data-testid="user-login" />
          <input type="password" value={form.password} onChange={(e) => setForm({ ...form, password: e.target.value })} placeholder={form.id ? "Nova senha (opcional)" : "Senha"} className="w-full bg-zinc-900 border border-zinc-800 rounded px-3 py-2 text-white text-sm" data-testid="user-password" />
          <select value={form.role} onChange={(e) => setForm({ ...form, role: e.target.value })} className="w-full bg-zinc-900 border border-zinc-800 rounded px-3 py-2 text-white text-sm">
            <option value="admin">Administrador</option><option value="vendedor">Vendedor</option><option value="producao">Produção</option>
          </select>
          <label className="flex items-center gap-2 text-white text-sm"><input type="checkbox" checked={form.active} onChange={(e) => setForm({ ...form, active: e.target.checked })} /> Ativo</label>
          <button onClick={save} data-testid="user-save" className="w-full bg-gradient-to-r from-pink-500 to-cyan-500 text-white font-bold py-2 rounded">Salvar</button>
        </div>
        <div className="md:col-span-2 card-riosul overflow-x-auto">
          <table className="w-full text-sm">
            <thead className="text-xs text-zinc-500 uppercase"><tr><th className="text-left px-3 py-2">Nome</th><th>Login</th><th>Perfil</th><th></th></tr></thead>
            <tbody>{list.map((u) => (
              <tr key={u.id} className="border-t border-zinc-800/60"><td className="px-3 py-2 text-white">{u.name}</td><td className="text-zinc-400">{u.login}</td>
                <td><span className={`text-xs px-2 py-1 rounded ${u.role === "admin" ? "bg-pink-500/20 text-pink-300" : "bg-cyan-500/20 text-cyan-300"}`}>{u.role}</span></td>
                <td className="text-right pr-3"><div className="inline-flex items-center gap-3"><button onClick={() => setForm({ ...u, password: "" })} className="text-cyan-400" title="Editar" data-testid={`edit-user-${u.id}`}><Edit size={14} /></button><button onClick={() => setConfirmDel(u)} className="text-red-400 hover:text-red-300" title="Excluir funcionário e dados" data-testid={`delete-user-${u.id}`}><Trash2 size={14} /></button></div></td>
              </tr>
            ))}</tbody>
          </table>
        </div>
      </div>
      {confirmDel && (
        <div className="fixed inset-0 z-50 bg-black/70 flex items-center justify-center p-4" onClick={() => setConfirmDel(null)}>
          <div className="card-riosul p-6 max-w-lg w-full" onClick={(e) => e.stopPropagation()} data-testid="confirm-delete-user-modal">
            <div className="flex items-center gap-3 mb-3">
              <div className="p-2 rounded-full bg-red-500/15 text-red-400"><Trash2 size={20} /></div>
              <h2 className="text-lg font-bold text-white">Excluir funcionário e todos os dados</h2>
            </div>
            <p className="text-sm text-zinc-300 mb-2">Tem certeza que deseja excluir permanentemente <b className="text-cyan-300">{confirmDel.name}</b>?</p>
            <p className="text-xs text-red-300 mb-5">Esta ação apagará o cadastro, todas as vendas desse funcionário, vales, pedidos Shopee importados por ele e arquivos anexados. Não pode ser desfeita.</p>
            <div className="flex justify-end gap-2">
              <button onClick={() => setConfirmDel(null)} data-testid="cancel-delete-user" className="px-4 py-2 rounded text-sm font-bold bg-zinc-800 text-white hover:bg-zinc-700">Não</button>
              <button onClick={removeUser} data-testid="confirm-delete-user" className="px-4 py-2 rounded text-sm font-bold bg-red-500 text-white hover:bg-red-600">Sim, apagar tudo</button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
