const { Client, LocalAuth } = require('whatsapp-web.js');
const qrcode = require('qrcode-terminal');
const express = require('express');
const cors = require('cors');
const axios = require('axios');

const app = express();
app.use(cors());
app.use(express.json());

const PORT = 3001;
const PYTHON_BACKEND_URL = 'http://localhost:8000/api/webhooks/whatsapp';

let currentQR = null;
let isConnected = false;

console.log('Inicializando cliente do WhatsApp...');

// Inicializa o cliente com autenticação local (salva a sessão na pasta .wwebjs_auth)
const client = new Client({
    authStrategy: new LocalAuth(),
    puppeteer: {
        args: ['--no-sandbox', '--disable-setuid-sandbox']
    }
});

// Quando o QR Code for gerado
client.on('qr', (qr) => {
    console.log('\nEscaneie o QR Code abaixo com o seu WhatsApp:');
    qrcode.generate(qr, { small: true });
    currentQR = qr; // Salva para o frontend poder consultar
});

// Quando o WhatsApp conectar com sucesso
client.on('ready', () => {
    console.log('\n✅ WhatsApp conectado com sucesso!');
    currentQR = null;
    isConnected = true;
});

client.on('disconnected', (reason) => {
    console.log('\n❌ WhatsApp desconectado:', reason);
    isConnected = false;
});

// Quando receber uma mensagem do WhatsApp
client.on('message', async (msg) => {
    // Ignora mensagens de grupos ou status por enquanto
    if (msg.isStatus || msg.from.includes('@g.us')) return;

    console.log(`📩 Nova mensagem de ${msg.from}: ${msg.body}`);

    // Encaminha a mensagem para o seu backend Python
    try {
        await axios.post(PYTHON_BACKEND_URL, {
            from: msg.from.replace('@c.us', ''),
            body: msg.body,
            timestamp: msg.timestamp
        });
    } catch (error) {
        console.error('Erro ao repassar mensagem para o Python:', error.message);
    }
});

// Inicia o bot
client.initialize();

// ==========================================
// Rotas da API Express (Para o seu Python usar)
// ==========================================

// Rota para o frontend pegar o QR Code
app.get('/api/qr', (req, res) => {
    if (isConnected) {
        return res.json({ connected: true, qr: null });
    }
    return res.json({ connected: false, qr: currentQR });
});

// Rota para o frontend ou Python saber se tá online
app.get('/api/status', (req, res) => {
    res.json({ connected: isConnected });
});

// Rota para o Python mandar mensagem
app.post('/api/send', async (req, res) => {
    if (!isConnected) {
        return res.status(400).json({ error: 'WhatsApp não está conectado' });
    }

    const { phone, message } = req.body;

    if (!phone || !message) {
        return res.status(400).json({ error: 'Telefone e mensagem são obrigatórios' });
    }

    try {
        // O whatsapp-web.js exige que o número termine com @c.us
        // Exemplo de telefone esperado (Brasil): 5511999999999
        let formattedPhone = phone;
        if (!formattedPhone.includes('@c.us')) {
            formattedPhone = `${formattedPhone}@c.us`;
        }

        await client.sendMessage(formattedPhone, message);
        console.log(`📤 Mensagem enviada para ${phone}`);
        
        return res.json({ success: true, message: 'Mensagem enviada!' });
    } catch (error) {
        console.error('Erro ao enviar mensagem:', error);
        return res.status(500).json({ error: 'Falha ao enviar mensagem', detail: error.message });
    }
});

app.listen(PORT, () => {
    console.log(`🚀 Serviço de API do WhatsApp rodando na porta ${PORT}`);
});
