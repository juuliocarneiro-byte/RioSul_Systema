# PRD — Rio Sul Festas & Gráfica

## Original Problem Statement
Sistema web completo para gestão de vendas, pedidos, clientes, funcionários e caixa da Rio Sul Festas & Gráfica com Central Shopee, tabelas de preços, PDFs de nota e ordem de produção.

## Etapa 2 (2026-09-23) — Melhorias
- Logo oficial da Rio Sul incorporada em toda a interface.
- Catálogo real semeado (16 categorias, 60+ produtos) com preços editáveis.
- Novos tipos de preço: `tiered` (apostilas por faixa de folhas) + flag `is_starting_price` ("a partir de") + campos `image_url` e `favorite` em produtos.
- Nova Venda com: cards com imagens, seção "Mais vendidos" (histórico real), filtro Favoritos, busca em produto/categoria/variação, calculadora M², calculadora por faixa (apostilas).
- Edição completa de pedido em `/vendas/:id/editar` (mesma UI da Nova Venda pré-preenchida — PUT mantém `order_number`).
- Duplicar pedido: `POST /api/sales/{id}/duplicate` gera novo pedido zerando pagamentos.
- Cliente criado automaticamente ao finalizar a venda (busca por telefone antes de duplicar).
- Instagram removido do cadastro de clientes.
- Anexos em pedidos: upload/paste (Ctrl+V)/arraste — armazenados em `/app/backend/uploads/` servidos via `/api/uploads/{fn}`.
- Nota do Pedido PDF (`GET /api/sales/{id}/pdf/note`) e Ordem de Produção PDF (`GET /api/sales/{id}/pdf/production`) via reportlab, layout branco A4 com logo.
- Módulo Tabelas de Preços (`/tabelas`): upload de imagem + gerador automático via Canvas (preços atuais do catálogo) + copiar/baixar/link.
- Central Shopee (`/shopee`) — substitui a antiga tela ZPL:
  - Upload de ZIP com validações (extensão, magic bytes PK, path traversal, limites de tamanho/arquivos).
  - Extração página a página de PDFs; identificação automática de cliente + nº do pedido via pdfplumber (regex + fallback SHIP TO).
  - Deduplicação por número + status "não identificado" quando faltar dado.
  - Anexar imagens do produto por pedido (upload).
  - Ficha de separação PDF (grande, com imagem) + PDFs em lote (Etiquetas / Fichas / Ambos) agrupados por cliente.
  - Status internos: AGUARDANDO IMAGEM → PRONTO PARA PRODUÇÃO → EM PRODUÇÃO → PRODUZIDO → SEPARADO → DESPACHADO.
  - Filtros por status/cliente/nº, histórico persistido no banco.
- Configurações agora inclui CNPJ e email; footer do PDF configurável.

## Test Credentials
- Admin: festasegraficariosul@gmail.com / RioSul@2026
- Vendedor: vendedor@riosul.com / Vendedor@2026

## Backend endpoints novos
- `POST /api/uploads`, `GET /api/uploads/{fn}`
- `PUT /api/products/{pid}/favorite`
- `POST /api/sales/{sid}/duplicate`, `POST/DELETE /api/sales/{sid}/attachments`
- `GET /api/sales/{sid}/pdf/note`, `.../pdf/production`
- `CRUD /api/price-tables`
- `POST /api/shopee/import`, `GET/PUT/DELETE /api/shopee/orders/{oid}`, `POST /api/shopee/orders/{oid}/images`, `GET /api/shopee/orders/{oid}/ficha`, `POST /api/shopee/batch-pdf`

## Backlog
- P1: Combos automáticos com itens no carrinho, Wire-O/Espiral/Capa como adicionais visíveis nas apostilas.
- P1: Compartilhamento via Web Share API (WhatsApp direto) para tabelas.
- P2: Auditoria detalhada com diff de campos, filtros de período rápido no dashboard.
- P2: Notificações WhatsApp automáticas de status.

## Etapa 3 (2026-02) — Kanban Pedidos/Produção
- Busca por número do pedido, cliente, telefone, produto e observações (normalização acento-insensível).
- Filtros rápidos: Hoje, Atrasados, Aguardando cliente. "Mais filtros": Vendedor, Status real, Prazo.
- Colunas visuais agrupadas (sem alterar status no banco):
  - "ARTE EM CRIAÇÃO / AGUARDANDO ARTE" mostra ambos os status; drop mapeia para "ARTE EM CRIAÇÃO".
  - "EM PRODUÇÃO / ARTE APROVADA" mostra ambos; drop mapeia para "EM PRODUÇÃO".
- Nova coluna derivada "EM ATRASO" (somente visualização, não permite drop) mostrando pedidos com `delivery_date` vencido e status ≠ ENTREGUE.
- Coluna "ENTREGUE HOJE" mostra apenas pedidos com `delivered_at` = data local de hoje.
- Backend: `PUT /api/sales/{sid}/status` grava `delivered_at` (ISO now) ao mover para ENTREGUE e faz `$unset` caso saia de ENTREGUE. Dados históricos preservados.
- Lista (view "Lista") também respeita busca/filtros.

## Etapa 5 (2026-02) — Exclusão de Funcionário com Cascata
- Funcionários agora têm lixeira ao lado do botão de edição, disponível na tela administrativa.
- Modal Sim/Não avisa que a exclusão é permanente e detalha o que será removido.
- `DELETE /api/users/{uid}/hard` permite apenas admin, bloqueia autoexclusão e remove o usuário, vendas vinculadas, vales, pedidos Shopee importados por ele, auditorias relacionadas e arquivos anexados.
- Clientes e produtos compartilhados não são removidos automaticamente, pois podem estar vinculados a outros registros.
- Testado pelo testing agent: backend 6/6 testes, frontend smoke + fluxo completo de confirmação aprovados.


