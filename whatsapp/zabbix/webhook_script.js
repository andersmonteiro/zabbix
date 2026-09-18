// ─────────────────────────────────────────────────────────────────────────────
// Natverk — Script do Media Type WhatsApp Webhook
// ─────────────────────────────────────────────────────────────────────────────
// Cole este script no campo "Script" do Media Type no Zabbix.
// ─────────────────────────────────────────────────────────────────────────────
try {
    var params = JSON.parse(value);

    var webhookUrl   = params.webhook_url;
    var webhookToken = params.webhook_token;

    // Remove parâmetros internos antes de enviar
    delete params.webhook_url;
    delete params.webhook_token;

    // Garante que status, severity e subject chegam sempre preenchidos
    params.status   = params.status   || 'PROBLEM';
    params.severity = params.severity || 'average';
    params.subject  = params.subject  || params.trigger_name || 'Alerta Zabbix';

    var request = new HttpRequest();
    request.addHeader('Content-Type: application/json');
    request.addHeader('X-Webhook-Token: ' + webhookToken);

    Zabbix.log(4, '[WhatsApp Webhook] Enviando para: ' + webhookUrl);
    Zabbix.log(4, '[WhatsApp Webhook] Payload: ' + JSON.stringify(params));

    var response = request.post(webhookUrl, JSON.stringify(params));
    var status   = request.getStatus();

    Zabbix.log(4, '[WhatsApp Webhook] HTTP ' + status + ' — Resposta: ' + response);

    if (status !== 200 && status !== 207) {
        throw 'Webhook retornou HTTP ' + status + ': ' + response;
    }

    return response;

} catch (error) {
    Zabbix.log(3, '[WhatsApp Webhook] Erro: ' + error);
    throw 'Falha ao enviar para o webhook: ' + error;
}
