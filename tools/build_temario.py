"""Genera el índice de diapositivas de SSDD y las sugerencias por pregunta.

Las sugerencias son orientativas: se calculan con un mapeo heurístico bilingüe
entre el texto de cada pregunta (y su respuesta correcta) y el texto extraído de
los PDFs del temario. El resultado se guarda en app/data/ssdd_temario.json y los
PDFs se copian a app/temario/ssdd/ para que la app desplegada sea autocontenida.
"""

import json, re, subprocess, math, unicodedata
from pathlib import Path
from collections import Counter

ROOT=Path(__file__).resolve().parent.parent
DECKS=[('intro','Introducción y conceptos básicos'),('indirect','Comunicación indirecta'),('protocol-design','Diseño de protocolos'),('remote-invocation','Invocación remota')]

# canonical concept aliases: Spanish and English. Add key forms; tokenizer will stem fallback.
CONCEPTS={
 'system':['sistema','sistemas','system','systems'],
 'distributed':['distribuido','distribuida','distribuidos','distribuidas','distribucion','distributed','distribution','distributing'],
 'application':['aplicacion','aplicaciones','application','applications','app','apps'],
 'middleware':['middleware','middlewares'],
 'transparency':['transparencia','transparente','transparent','transparency','transparencias'],
 'access':['acceso','accesos','access'],
 'location':['localizacion','localización','location','ubicacion','ubicación'],
 'migration':['migracion','migración','migration'],
 'replication':['replicacion','replicación','replication','replica','réplica','replicas','réplicas','replicate'],
 'relocation':['reubicacion','reubicación','relocation'],
 'concurrency':['concurrencia','concurrente','concurrent','concurrency'],
 'consistency':['consistencia','consistente','consistency','consistent'],
 'failure':['fallo','fallos','falla','fallas','failure','failures','fail','fails','failed'],
 'independent':['independiente','independientes','independent'],
 'heterogeneity':['heterogeneidad','heterogeneo','heterogenea','heterogeneous','heterogeneity'],
 'scalability':['escalabilidad','escalable','scalability','scalable','grow','growth'],
 'reliability':['fiabilidad','fiable','reliability','reliable'],
 'availability':['disponibilidad','disponible','availability','available'],
 'advantage':['ventaja','ventajas','cualidad','cualidades','caracteristica','caracteristicas','característica','características','advantage','advantages','beneficio','beneficios','benefit','benefits'],
 'security':['seguridad','seguro','security','secure'],
 'performance':['rendimiento','prestaciones','performance'],
 'latency':['latencia','latency'],
 'bandwidth':['ancho','banda','bandwidth'],
 'resource':['recurso','recursos','resource','resources'],
 'sharing':['compartir','compartido','compartida','compartición','sharing','share','shared'],
 'service':['servicio','servicios','service','services'],
 'server':['servidor','servidores','server','servers'],
 'client':['cliente','clientes','client','clients'],
 'protocol':['protocolo','protocolos','protocol','protocols'],
 'message':['mensaje','mensajes','message','messages','messaging'],
 'process':['proceso','procesos','process','processes'],
 'program':['programa','programas','program','programs'],
 'network':['red','redes','network','networks','networking'],
 'node':['nodo','nodos','node','nodes'],
 'computer':['ordenador','computadora','computador','computer','computers','machine','machines'],
 'cloud':['nube','nubes','cloud','clouds'],
 'iaas':['iaas','infrastructure as a service','infraestructura como servicio'],
 'paas':['paas','platform as a service','plataforma como servicio'],
 'saas':['saas','software as a service','software como servicio'],
 'internet':['internet','web'],
 'iot':['iot','internet of things','internet de las cosas'],
 'grid':['grid','grid computing'],
 'mobile':['movil','móvil','mobile'],
 'parallel':['paralelo','paralela','parallel','parallelism'],
 'goal':['objetivo','meta','goal','purpose'],
 'cost':['coste','costo','cost','costs'],
 'security_comm':['comunicaciones','communications'],
 'fault_tolerance':['tolerancia','tolerante','fault','tolerance','tolerant'],
 'fault':['fallo','fallos','error','errores','fault','faults','error','errors'],
 'partial':['parcial','parciales','partial'],
 'global_clock':['reloj','relojes','clock','clocks','global clock'],
 'synchronization':['sincronizacion','sincronización','sincronizar','synchronization','synchronize','synchronisation','sync'],
 'sockets':['socket','sockets'],
 'ipc':['ipc','interprocess','inter-process'],
 'tcp':['tcp'],
 'udp':['udp'],
 'rpc':['rpc','remote procedure call','llamada a procedimiento remoto'],
 'rmi':['rmi','remote method invocation','invocacion remota de metodos','invocación remota de métodos'],
 'remote':['remoto','remota','remotos','remotas','remote'],
 'invocation':['invocacion','invocación','invocar','invoke','invocation','call','llamada','llamadas'],
 'request':['peticion','petición','solicitud','request','requests'],
 'reply':['respuesta','respuestas','reply','replies','response','responses'],
 'ack':['ack','acknowledgement','acuse','confirmacion','confirmación'],
 'rra':['rra','request-reply-ack','request reply ack'],
 'rr':['rr','request-reply'],
 'idempotent':['idempotente','idempotentes','idempotent','idempotency'],
 'retry':['reintento','reintentos','retry','retries'],
 'duplicate':['duplicado','duplicados','duplicada','duplicate','duplicates','duplicate filter','filtro de duplicados'],
 'elimination':['eliminacion','eliminación','eliminar','elimination','eliminate','remove','removal'],
 'at_most_once':['at-most-once','at most once','como mucho una vez'],
 'at_least_once':['at-least-once','at least once','al menos una vez'],
 'exactly_once':['exactly-once','exactly once','exactamente una vez'],
 'stub':['stub','stubs'],
 'proxy':['proxy','proxies','subrogado','subrogado local'],
 'skeleton':['skeleton','esqueleto'],
 'dispatcher':['dispatcher','despachador'],
 'interface':['interfaz','interfaces','interface','interfaces'],
 'idl':['idl','interface definition language','lenguaje de definicion de interfaces','lenguaje de definición de interfaces'],
 'marshalling':['marshalling','marshaling','marshal','unmarshal','serializacion','serialización','serialization','serialize','serializacion de datos'],
 'serialization':['serializacion','serialización','serialization','serialize','serializacion de datos'],
 'binary':['binario','binaria','binary'],
 'data':['dato','datos','data'],
 'type':['tipo','tipos','type','types'],
 'field':['campo','campos','field','fields'],
 'identifier':['identificador','identificadores','identifier','identifiers','id'],
 'sequence':['secuencia','secuencias','sequence','sequences'],
 'bytes':['byte','bytes','octeto','octetos'],
 'variable':['variable','variables'],
 'topology':['topologia','topología','topology'],
 'length':['longitud','tamano','tamaño','length','size'],
 'syntax':['sintaxis','syntax'],
 'semantics':['semantica','semántica','semantics','semantic'],
 'state':['estado','estados','state','states'],
 'transition':['transicion','transición','transition','transitions'],
 'diagram':['diagrama','diagramas','diagram','diagrams'],
 'timer':['temporizador','temporizadores','timer','timers','timeout','tiemout','tiemou','time-out'],
 'lost':['perdido','perdida','pérdida','perdidos','lost','loss'],
 'history':['historial','historia','history'],
 'guarantee':['garantia','garantía','garantias','garantías','guarantee','guarantees','guaranteed'],
 'tftp':['tftp','trivial file transfer protocol'],
 'protocol_buffers':['protocol buffers','protobuf','protobufs','google protocol buffers','repeated','required','optional','oneof','varint','reserved'],
 'struct':['struct','python struct','estructura','estructuras'],
 'grpc':['grpc'],
 'onc_rpc':['onc rpc','onc','rpc 1057','sun rpc'],
 'xdr':['xdr','external data representation'],
 'rpcbind':['rpcbind','portmapper','portmap','binder','binder'],
 'binding':['binding','binder','enlace','vinculacion','vinculación','bind'],
 'registration':['registro','registrar','registration','register'],
 'resolution':['resolucion','resolución','resolution','resolve'],
 'endpoint':['endpoint','punto final','host','puerto','port'],
 'reference':['referencia','referencias','reference','references'],
 'object':['objeto','objetos','object','objects'],
 'class':['clase','clases','class','classes'],
 'method':['metodo','método','metodos','métodos','method','methods'],
 'procedure':['procedimiento','procedimientos','procedure','procedures'],
 'function':['funcion','función','funciones','function','functions'],
 'async':['asincrono','asíncrono','asincrona','asíncrona','asynchronous','async'],
 'sync':['sincrono','síncrono','sincrona','síncrona','synchronous','sync','blocking','bloqueante'],
 'blocking':['bloqueante','blocking','block'],
 'nonblocking':['no bloqueante','non-blocking','nonblocking'],
 'thread':['hilo','hilos','thread','threads'],
 'pool':['pool','grupo','pool de hilos'],
 'promise':['promesa','promesas','promise','promises','pipelining','pipeline'],
 'capabilities':['capacidades','capability','capabilities'],
 'performance_comparison':['comparacion','comparación','comparison','rendimiento'],
 'rest':['rest','representational state transfer'],
 'crud':['crud'],
 'http':['http','https'],
 'get':['get'],
 'post':['post'],
 'put':['put'],
 'delete':['delete','borrar'],
 'resource_method':['recurso','recursos','resource','resources'],
 'soap':['soap'],
 'xml':['xml'],
 'xmlrpc':['xml-rpc','xmlrpc'],
 'web_service':['servicio web','servicios web','web service','web services'],
 'wsdl':['wsdl'],
 'indirect':['indirecta','indirecto','indirectas','indirectos','indirect'],
 'direct':['directa','directo','directas','directos','direct'],
 'fallacy':['falacia','falacias','fallacy','fallacies'],
 'assume':['asumir','asumimos','suponer','assume','assumption','assumptions'],
 'change':['cambiar','cambia','cambio','cambios','change','changes','changing'],
 'communication':['comunicacion','comunicación','comunicaciones','communication','communications','communicate'],
 'intermediary':['intermediario','intermediarios','intermediary','intermediaries','broker','brokers'],
 'broker':['broker','brokers','intermediario','intermediarios'],
 'decoupling':['desacoplamiento','desacoplar','desacoplado','decoupling','decouple','decoupled'],
 'time':['tiempo','tiempos','time','times'],
 'space':['espacio','space'],
 'suitable':['adecuado','adecuada','suitable','scenario','scenarios','escenario','escenarios'],
 'disadvantage':['desventaja','desventajas','disadvantage','disadvantages'],
 'overload':['sobrecarga','sobrecargar','overload','overloading'],
 'level_indirection':['nivel de indireccion','nivel de indirección','level of indirection','indirection'],
 'group':['grupo','grupos','group','groups','multicast','multidifusion','multidifusión'],
 'event':['evento','eventos','event','events','event-based','event based'],
 'publish':['publicar','publica','publicador','publicadores','publish','publisher','publishers','publication','publicaciones'],
 'subscribe':['suscribir','suscripcion','suscripción','subscripcion','subscripción','subscripciones','suscriptor','suscriptores','subscribe','subscriber','subscribers','subscription','subscriptions'],
 'pubsub':['publish-subscribe','pub-sub','pubsub','publicacion-suscripcion','publicación-suscripción'],
 'push':['push','empuje','envio directo','envío directo'],
 'pull':['pull','tirar','solicitud','peticion','petición'],
 'channel':['canal','canales','channel','channels','topic','topics','tema','temas'],
 'content':['contenido','contenidos','content','content-based','content based'],
 'filter':['filtro','filtros','filtrar','filter','filters','filtering'],
 'predicate':['predicado','predicados','predicate','predicates'],
 'value':['valor','valores','value','values'],
 'attribute':['atributo','atributos','attribute','attributes'],
 'web':['web','www'],
 'buffer':['buffer','buffers'],
 'query':['consulta','consultas','query','queries'],
 'constraint':['restriccion','restricción','restricciones','constraint','constraints'],
 'routing':['enrutamiento','encaminamiento','routing','route','routes'],
 'flooding':['inundacion','inundación','flooding','flood'],
 'icestorm':['icestorm','ice storm'],
 'zeroc':['zeroc','zero c','ice'],
 'message_queue':['cola','colas','cola de mensajes','colas de mensajes','message queue','message queues','queue','queues'],
 'fifo':['fifo','first in first out'],
 'priority':['prioridad','prioridades','priority','priorities'],
 'selection':['seleccion','selección','selection','select'],
 'rabbitmq':['rabbitmq','amqp'],
 'producer':['productor','productores','producer','producers'],
 'consumer':['consumidor','consumidores','consumer','consumers'],
 'work':['trabajo','trabajos','work','works','worker','workers'],
 'work_queue':['work queue','work queues','cola de trabajo','colas de trabajo'],
 'celery':['celery','task queue','cola de tareas'],
 'kafka':['kafka','event streaming','streaming','flujo de eventos'],
 'partition':['particion','partición','particiones','partition','partitions'],
 'offset':['offset','desplazamiento'],
 'syntax_semantics':['sintaxis','semantica','semántica','syntax','semantics'],
 'design':['diseno','diseño','disenar','diseñar','design','designs','designing'],
 'purpose':['proposito','propósito','purpose','goal','objetivo','meta'],
 'nonfunctional':['no funcional','non-functional','nonfunctional','calidad','quality'],
 'security_protocol':['seguridad','security','cifrado','cifrar','encryption','encrypt','autenticacion','autenticación','authentication','integridad','integrity','corrupcion','corrupción','corruption'],
 'api':['api','apis'],
 'open':['abierto','abierta','open','public'],
 'public_protocol':['protocolo abierto','protocolo publico','protocolo público','open protocol','public protocol'],
 'transparency_protocol':['transparencia','transparency'],
 'tcp_ip':['tcp/ip','tcp ip','stack','pila'],
 'python':['python'],
 'c':['c','lenguaje c'],
 'java':['java'],
 'programming_language':['lenguaje','lenguajes','language','languages'],
 'code':['codigo','código','code'],
 'compile':['compilar','compilacion','compilación','compile','compilation'],
 'generate':['generar','generacion','generación','generate','generation'],
 'idempotencia':['idempotencia'],
 'request_reply':['request-reply','solicitud-respuesta','peticion-respuesta','petición-respuesta'],
 'response_time':['tiempo de respuesta','response time'],
 'mean':['media','promedio','mean','average'],
 'local_call':['llamada local','local call'],
 'remote_call':['llamada remota','remote call'],
 'factorial':['factorial'],
 'loopback':['loopback','bucle local'],
 'in_process':['en proceso','in-process','in process'],
 'node_remote':['otro nodo','another node','remote node'],
 'ice':['ice','zeroc ice'],
 'servant':['servant','sirviente'],
 'adapter':['adapter','adaptador','object adapter','adaptador de objetos'],
 'factory':['factory','fabrica','fábrica'],
 'lifecycle':['ciclo de vida','lifecycle','life cycle'],
 'garbage':['basura','garbage','garbage collection','recoleccion de basura','recolección de basura'],
 'distributed_garbage':['basura distribuida','distributed garbage'],
 'remote_object':['objeto remoto','objetos remotos','remote object','remote objects'],
 'remote_reference':['referencia remota','referencias remotas','remote reference','remote references'],
 'endpoint_remote':['endpoint','host','port','protocol'],
 'location_transparency':['transparencia de localizacion','transparencia de localización','location transparency'],
 'dynamic_binding':['binding dinamico','binding dinámico','dynamic binding'],
 'temporary_binding':['binding temporal','temporary binding','temporal','temporary'],
 'per_call':['por llamada','per call','per-call'],
 'server_reference':['referencia del servidor','server reference'],
 'rpcinfo':['rpcinfo'],
 'register_server':['registrar servidor','register server','registration'],
 'resolve_binding':['resolver binding','resolve binding','resolution'],
 'synchronous':['sincrono','síncrono','synchronous'],
 'asynchronous':['asincrono','asíncrono','asynchronous'],
 'dispatch':['despacho','despachar','dispatch','dispatching'],
 'thread_pool':['pool de hilos','thread pool','limited thread pool'],
 'block':['bloquear','bloquea','block','blocks','blocked'],
 'free_thread':['hilo libre','free thread','thread is not free'],
 'callback':['callback','retrollamada','llamada de retorno'],
 'future':['futuro','future','futures'],
 'promise_pipelining':['promise pipelining','pipelining','pipeline'],
 'serialization_format':['formato de serializacion','formato de serialización','serialization format'],
 'rmi_middleware':['middleware rmi','rmi middleware'],
 'oo':['orientado a objetos','orientada a objetos','object oriented','object-oriented','oo','poo'],
 'inheritance':['herencia','inheritance','inherit'],
 'polymorphism':['polimorfismo','polymorphism'],
 'encapsulation':['encapsulacion','encapsulación','encapsulation'],
 'interface_definition':['definicion de interfaz','definición de interfaz','interface definition'],
 'java_rmi':['java rmi','java.rmi'],
 'registry':['registro','registry','rmiregistry','binder'],
 'naming':['nombrado','nombres','naming','name','names'],
 'reference_remote':['referencia remota','remote reference'],
 'stub_skeleton':['stub','skeleton','esqueleto'],
 'proxy_stub':['proxy','stub'],
 'object_adapter':['object adapter','adaptador de objetos'],
 'servant_dispatch':['servant','dispatch'],
 'capnproto':['capn proto','cap’n proto','capnproto'],
 'capability':['capacidad','capacidades','capability','capabilities'],
 'promise_return':['promesa','promise'],
 'pipelining':['pipelining','pipeline'],
 'performance':['rendimiento','prestaciones','performance'],
 'comparison':['comparacion','comparación','comparison','compare'],
 'cost_remote':['coste','coste de','cost','cost of'],
 'rest_style':['estilo arquitectonico','estilo arquitectónico','architectural style','rest'],
 'resource_uri':['uri','url','recurso','resource'],
 'method_http':['metodo http','método http','http method','get','post','put','delete'],
 'crud':['crud','create','read','update','delete'],
 'uniform_interface':['interfaz uniforme','uniform interface'],
 'stateless':['sin estado','stateless'],
 'cache':['cache','cacheable','almacenamiento en cache','almacenamiento en caché'],
 'layered':['por capas','layered','layers'],
 'code_on_demand':['codigo bajo demanda','código bajo demanda','code on demand'],
 'rest_not_rpc':['rest no es rpc','rest is not rpc'],
 'soap_web':['soap','web service','servicio web'],
 'xml_rpc':['xml-rpc','xmlrpc'],
 'wsdl':['wsdl'],
 'uddi':['uddi'],
 'json':['json'],
 'rpc_style':['estilo','style','rpc'],
 'protocol_example':['ejemplo','example','ejemplos','examples'],
 'diy':['diy','hazlo tu mismo','hazlo tú mismo'],
 'what_learned':['que has aprendido','qué has aprendido','what have you learned'],
 'reference':['referencia','referencias','reference','references','bibliografia','bibliografía'],
}

# Build token -> canonical. Solo alias de una palabra: las frases se dejan
# a sus palabras sueltas para no asignar significados incorrectos.
TOKEN_CANON={}
for canon, aliases in CONCEPTS.items():
    for a in aliases:
        a=unicodedata.normalize('NFD',a).encode('ascii','ignore').decode().lower()
        words=re.findall(r"[a-z0-9]+",a)
        if len(words)==1 and len(words[0])>1:
            TOKEN_CANON.setdefault(words[0],canon)
# direct technical tokens
for t in ['rpc','rmi','tcp','udp','ip','http','https','json','xml','soap','rest','grpc','tftp','xdr','onc','rpcbind','portmapper','fifo','amqp','kafka','rabbitmq','celery','icestorm','zeroc','idl','api','uri','url','crud','wsdl','uddi','iaas','paas','saas','iot','diy']:
    TOKEN_CANON.setdefault(t,t)


GENERIC_TOPIC = set('system distributed application process message network service client server data type field state time resource function object method program code reference interface'.split())
TOPIC_TERMS = {
 'intro': set('system distributed application middleware transparency access location migration replication relocation concurrency consistency failure independent heterogeneity scalability reliability availability security performance resource sharing service server client protocol message process program network node computer cloud iaas paas saas internet iot grid mobile parallel goal cost fault_tolerance partial global_clock sockets ipc tcp udp rpc remote invocation client_server'.split()),
 'indirect': set('indirect direct communication intermediary push pull broker decoupling time space suitable disadvantage overload level_indirection group event publish subscribe pubsub channel content filter query constraint routing flooding icestorm zeroc message_queue fifo priority selection rabbitmq producer consumer work work_queue celery kafka partition offset'.split()),
 'protocol-design': set('protocol syntax semantics state transition diagram timer tftp protocol_buffers struct serialization marshalling binary data type field length design nonfunctional security_protocol api open public_protocol tcp_ip programming_language code compile generate identifier sequence bytes variable'.split()),
 'remote-invocation': set('rpc rmi remote invocation request reply ack rra rr idempotent retry duplicate at_most_once at_least_once exactly_once stub proxy skeleton dispatcher interface idl binding registration resolution endpoint reference object class method procedure function async sync blocking nonblocking thread pool promise capabilities performance_comparison rest crud http get post put delete soap xml xmlrpc web_service wsdl grpc onc_rpc xdr rpcbind java_rmi ice capnproto capability pipelining performance comparison cost_remote local_call remote_call factorial loopback in_process node_remote rmi_middleware oo inheritance polymorphism encapsulation interface_definition registry naming remote_object remote_reference location_transparency dynamic_binding temporary_binding per_call server_reference rpcinfo register_server resolve_binding synchronous asynchronous dispatch thread_pool block free_thread callback future promise_pipelining serialization_format capability promise_return timer timeout lost history guarantee failure'.split()),
}
SPECIFIC = set().union(*TOPIC_TERMS.values()) | set('idempotent retry duplicate pubsub icestorm zeroc rabbitmq celery kafka tftp protocol_buffers struct grpc onc_rpc xdr rpcbind soap xmlrpc wsdl capnproto rest http crud fifo amqp'.split())

STOP=set('''a al algo algun alguna algunas alguno algunos ante antes aquel aquella aquellas aquellos aqui asi aun aunque cada como con contra cual cuales cuando de del desde donde dos el ella ellas ello ellos en entre era eran es esa esas ese eso esos esta estaba estado estan estar estas este esto estos estoy fue fueron ha hace hacen hacer hacia han hasta hay la las le les lo los mas me mi mis mucho muy nada ni no nos nosotros o os otra otras otro otros para pero poco por porque que quien quienes se sea sean segun ser si sido sin sobre son su sus tambien tan tanto te tiene tienen todo todos tu tus un una unas uno unos y ya you your the a an and or of to in on for with by from as is are was were be been being this that these those it its at into about than then so such can could may might will would should do does did not no only also more most very much many few some any each other another same different using used use'''.split())

def normalize(text):
    text=unicodedata.normalize('NFD',text).encode('ascii','ignore').decode().lower()
    return text

def stem(t):
    # simple prefix normalization to merge plurals/forms
    if len(t)<=4: return t
    return t[:6]

def tokens(text, canon=True):
    text=normalize(text)
    out=[]
    for t in re.findall(r"[a-z0-9]+", text):
        if t in STOP or len(t)<2: continue
        c=TOKEN_CANON.get(t)
        out.append(c if c else stem(t))
    return out

def pdf_pages(deck):
    path=ROOT/'temario'/'ssdd'/f'{deck}.pdf'
    n=int(subprocess.run(['pdfinfo',str(path)],capture_output=True,text=True).stdout.split('Pages:')[1].split()[0])
    pages=[]
    for p in range(1,n+1):
        text=subprocess.run(['pdftotext','-f',str(p),'-l',str(p),'-layout',str(path),'-'],capture_output=True,text=True).stdout
        pages.append(text)
    return pages

def slide_title(text, page):
    lines=[re.sub(r'\s+',' ',l).strip() for l in text.splitlines() if l.strip()]
    # remove known headers/footers
    lines=[l for l in lines if not re.search(r'Version \d|Distributed Systems ::|Instructor.s Guide|David\.Villa|Pearson|©',l)]
    title=' '.join(lines[:2]) if lines else f'Diapositiva {page}'
    return title[:160]

# build index
slides=[]
for deck,title_es in DECKS:
    pages=pdf_pages(deck)
    for i,text in enumerate(pages,1):
        title=slide_title(text,i)
        body=tokens(text)
        title_tokens=tokens(title)
        slides.append({'deck':deck,'deck_title':title_es,'page':i,'title':title,'body':body,'title_tokens':title_tokens})
N=len(slides)
df=Counter()
for s in slides:
    df.update(set(s['body'])|set(s['title_tokens']))
idf={t:math.log((N+1)/(c+1))+1 for t,c in df.items()}


# Refuerzos manuales: conceptos que deben llevar a páginas concretas del temario.
CONCEPT_BOOSTS = {
    'middleware': [('intro', 26), ('intro', 27), ('intro', 28), ('intro', 29)],
    'transparency': [('intro', 24), ('intro', 25)],
    'heterogeneity': [('intro', 18), ('intro', 19)],
    'scalability': [('intro', 20)],
    'concurrency': [('intro', 21), ('intro', 22)],
    'reliability': [('intro', 23)],
    'availability': [('intro', 11), ('intro', 23)],
    'cloud': [('intro', 9), ('intro', 10)],
    'advantage': [('intro', 11)],
    'buffer': [('protocol-design', 17), ('protocol-design', 18), ('protocol-design', 19)],
    'repeated': [('protocol-design', 19)],
    'required': [('protocol-design', 19)],
    'optional': [('protocol-design', 19)],
    'sockets': [('intro', 32), ('intro', 33), ('intro', 34)],
    'rpc': [('remote-invocation', 15), ('remote-invocation', 16), ('remote-invocation', 17)],
    'rmi': [('remote-invocation', 28), ('remote-invocation', 29), ('remote-invocation', 30), ('remote-invocation', 31), ('remote-invocation', 32)],
    'idempotent': [('remote-invocation', 12), ('remote-invocation', 13)],
    'duplicate': [('remote-invocation', 11), ('remote-invocation', 13)],
    'rra': [('remote-invocation', 10), ('remote-invocation', 11)],
    'timeout': [('remote-invocation', 6), ('remote-invocation', 11)],
    'timer': [('remote-invocation', 6), ('remote-invocation', 11)],
    'binding': [('remote-invocation', 41), ('remote-invocation', 42), ('remote-invocation', 43), ('remote-invocation', 46)],
    'rpcbind': [('remote-invocation', 44), ('remote-invocation', 45), ('remote-invocation', 46)],
    'rest': [('remote-invocation', 57), ('remote-invocation', 58), ('remote-invocation', 59)],
    'soap': [('remote-invocation', 61)],
    'xmlrpc': [('remote-invocation', 61)],
    'grpc': [('remote-invocation', 26), ('remote-invocation', 27)],
    'interface_definition': [('remote-invocation', 29)],
    'capnproto': [('remote-invocation', 51), ('remote-invocation', 52), ('remote-invocation', 53)],
    'protocol_buffers': [('protocol-design', 17), ('protocol-design', 18), ('protocol-design', 19)],
    'tftp': [('protocol-design', 4), ('protocol-design', 6), ('protocol-design', 13), ('protocol-design', 14)],
    'syntax': [('protocol-design', 5)],
    'semantics': [('protocol-design', 6)],
    'synchronization': [('protocol-design', 7), ('protocol-design', 8), ('protocol-design', 9), ('protocol-design', 10), ('protocol-design', 11), ('protocol-design', 12)],
    'struct': [('protocol-design', 21)],
    'indirect': [('indirect', 4), ('indirect', 5), ('indirect', 6), ('indirect', 9)],
    'direct': [('indirect', 4), ('indirect', 5), ('indirect', 6), ('indirect', 9)],
    'broker': [('indirect', 9), ('indirect', 15), ('indirect', 16)],
    'publish': [('indirect', 10), ('indirect', 11), ('indirect', 12), ('indirect', 13), ('indirect', 18), ('indirect', 19), ('indirect', 20)],
    'subscribe': [('indirect', 10), ('indirect', 11), ('indirect', 12), ('indirect', 13), ('indirect', 14), ('indirect', 18), ('indirect', 19)],
    'pubsub': [('indirect', 10), ('indirect', 11), ('indirect', 13), ('indirect', 14)],
    'channel': [('indirect', 13), ('indirect', 14)],
    'content': [('indirect', 13), ('indirect', 14), ('indirect', 17)],
    'filter': [('indirect', 13), ('indirect', 14), ('indirect', 17)],
    'predicate': [('indirect', 14), ('indirect', 17)],
    'message_queue': [('indirect', 22), ('indirect', 23), ('indirect', 24)],
    'work': [('indirect', 22), ('indirect', 23), ('indirect', 30)],
    'work_queue': [('indirect', 22), ('indirect', 23), ('indirect', 30)],
    'rabbitmq': [('indirect', 26), ('indirect', 27), ('indirect', 30)],
    'celery': [('indirect', 31)],
    'kafka': [('indirect', 32), ('indirect', 33), ('indirect', 34)],
    'icestorm': [('indirect', 18), ('indirect', 19), ('indirect', 20)],
    'zeroc': [('indirect', 18), ('indirect', 19), ('indirect', 20)],
    'lost': [('remote-invocation', 6), ('remote-invocation', 11)],
    'history': [('remote-invocation', 10), ('remote-invocation', 11)],
    'reply': [('remote-invocation', 7), ('remote-invocation', 8), ('remote-invocation', 9), ('remote-invocation', 10), ('remote-invocation', 11)],
    'marshalling': [('remote-invocation', 16), ('remote-invocation', 17), ('remote-invocation', 18)],
    'interface': [('remote-invocation', 29), ('remote-invocation', 31), ('remote-invocation', 32)],
    'idl': [('remote-invocation', 29)],
    'adapter': [('remote-invocation', 32)],
    'servant': [('remote-invocation', 32)],
    'registry': [('remote-invocation', 41), ('remote-invocation', 46)],
    'naming': [('remote-invocation', 41), ('remote-invocation', 46)],
    'async': [('remote-invocation', 47), ('remote-invocation', 48), ('remote-invocation', 49), ('remote-invocation', 50)],
    'synchronous': [('remote-invocation', 47), ('remote-invocation', 48), ('remote-invocation', 49)],
    'asynchronous': [('remote-invocation', 47), ('remote-invocation', 48), ('remote-invocation', 49), ('remote-invocation', 50)],
    'web_service': [('remote-invocation', 61)],
    'wsdl': [('remote-invocation', 61)],
    'security': [('protocol-design', 16)],
    'security_protocol': [('protocol-design', 16)],
    'design': [('protocol-design', 15), ('protocol-design', 16)],
    'protocol': [('protocol-design', 3), ('protocol-design', 15)],
    'purpose': [('protocol-design', 3)],
    'push': [('indirect', 24), ('indirect', 13), ('indirect', 19)],
    'pull': [('indirect', 24), ('indirect', 13), ('indirect', 19)],
    'event': [('indirect', 10), ('indirect', 12), ('indirect', 13), ('indirect', 14)],
}


STRONG_BOOSTS = {
    'grpc': [('remote-invocation', 26), ('remote-invocation', 27)],
    'timeout': [('remote-invocation', 6), ('remote-invocation', 11)],
    'timer': [('remote-invocation', 6), ('remote-invocation', 11)],
    'async': [('remote-invocation', 47), ('remote-invocation', 48), ('remote-invocation', 49), ('remote-invocation', 50)],
    'asynchronous': [('remote-invocation', 47), ('remote-invocation', 48), ('remote-invocation', 49), ('remote-invocation', 50)],
    'binding': [('remote-invocation', 41), ('remote-invocation', 42), ('remote-invocation', 43), ('remote-invocation', 46)],
    'registry': [('remote-invocation', 41), ('remote-invocation', 46)],
    'idl': [('remote-invocation', 29)],
    'interface': [('remote-invocation', 29), ('remote-invocation', 31)],
    'advantage': [('intro', 11)],
    'rabbitmq': [('indirect', 26), ('indirect', 27), ('indirect', 30)],
    'kafka': [('indirect', 32), ('indirect', 33), ('indirect', 34)],
}

EXCLUDE_TITLE_PAT=re.compile(r'^(contents|references?|credits|what have you learned)', re.I)


TOPIC_MARKERS = [
    ('remote-invocation', set('rpc rmi grpc stub skeleton idempotent rra onc_rpc xdr rpcbind binding rest soap xmlrpc capnproto proxy dispatcher async synchronous asynchronous dispatch future promise pipelining idl interface_definition object_adapter adapter servant remote_object remote_reference location_transparency dynamic_binding registry naming interface duplicate retry failure timeout timer lost history guarantee'.split())),
    ('protocol-design', set('protocol_buffers buffer tftp syntax semantics marshalling serialization struct design nonfunctional protocol purpose identifier sequence variable security security_protocol'.split())),
    ('indirect', set('indirect broker publish subscribe pubsub event channel content filter predicate value attribute message_queue queue rabbitmq celery kafka icestorm zeroc work_queue work producer consumer decoupling intermediary group multicast push pull'.split())),
    ('intro', set('middleware transparency heterogeneity scalability reliability availability cloud iaas paas saas parallel resource sharing sockets ipc concurrency consistency'.split())),
]

def classify_topic(query):
    for topic, markers in TOPIC_MARKERS:
        if any(t in markers for t in query):
            return topic
    return None

def score_question(q):
    qtext = q['text']
    ans = ' '.join(o['text'] for o in q['options'] if o['letter'] in q['answer'])
    opts = ' '.join(o['text'] for o in q['options'])
    qt = Counter(tokens(qtext))
    at = Counter(tokens(ans))
    ot = Counter(tokens(opts))
    query = Counter()
    for c, w in [(qt, 1.6), (at, 2.8), (ot, 0.35)]:
        for t, n in c.items():
            query[t] += n * w

    # Clasificación temática por marcadores de dominio (sin distractores).
    topic_query = Counter()
    for c, w in [(qt, 1.6), (at, 2.8)]:
        for t, n in c.items():
            topic_query[t] += n * w
    alltext = normalize(qtext + ' ' + ans)
    if re.search(r'comunicaci[oó]n\s+(?:in)?directa', alltext):
        topic = 'indirect'
    else:
        topic = classify_topic(topic_query)
    if topic is None and ('system' in topic_query or 'distributed' in topic_query):
        topic = 'intro'
    strong = topic is not None

    # Temas que no están cubiertos por estos cuatro temas del temario.
    if NEGATIVE_PAT.search(alltext):
        return [], None

    specific = sum(1 for t in topic_query if t in SPECIFIC)
    rare_specific = sum(1 for t in topic_query if t in SPECIFIC and idf.get(t, 1) > 2.6)

    scored = []
    for s in slides:
        title = s['title'].strip()
        if EXCLUDE_TITLE_PAT.match(title) or s['page'] == 1:
            continue
        if re.match(r'^(references?|bibliograf)', title, re.I):
            continue
        if re.search(r'\bdiy\b', title, re.I):
            continue
        if strong and s['deck'] != topic:
            continue
        body = Counter(s['body'])
        titlec = Counter(s['title_tokens'])
        score = 0.0
        for t, w in query.items():
            tf = body.get(t, 0) + 3 * titlec.get(t, 0)
            if tf:
                score += w * idf.get(t, 1.0) * math.log1p(tf)
        if not score:
            continue
        score /= math.sqrt(1 + len(s['body']) / 80)
        # Refuerzos manuales por concepto.
        for t, w in query.items():
            for deck, page in CONCEPT_BOOSTS.get(t, []):
                if s['deck'] == deck and s['page'] == page:
                    score += w * 3.0
            for deck, page in STRONG_BOOSTS.get(t, []):
                if s['deck'] == deck and s['page'] == page:
                    score += w * 8.0
        if strong and s['deck'] == topic:
            score *= 1.18
        scored.append((score, s))

    scored.sort(key=lambda x: -x[0])
    if (specific < 2 and rare_specific < 1 and not (topic and specific >= 1)) or (not scored or scored[0][0] < 12):
        return [], topic if strong else None

    # Máximo 3 diapositivas, evitando repetir la misma página y mezclando como mucho dos temas.
    result = []
    seen = set()
    deck_count = Counter()
    for score, s in scored:
        key = (s['deck'], s['page'])
        if key in seen:
            continue
        if deck_count[s['deck']] >= 2:
            continue
        seen.add(key)
        deck_count[s['deck']] += 1
        result.append({
            'deck': s['deck'],
            'page': s['page'],
            'title': s['title'],
            'score': round(score, 2),
        })
        if len(result) >= 3:
            break
    return result, topic if strong else None


# Patrón de temas no cubiertos por el temario actual.
NEGATIVE_PAT = re.compile(
    r'berkeley|sesgo\b|skew\b|vectorial|vector clock|lamport|bizantin|byzantin|'
    r'teorema cap|\bcap\b|consenso|consensus|replicaci|replication|'
    r'exclusion mutua|mutual exclusion|estados? global(?:es)?|global state|snapshot|'
    r'transaccion|transaction|two[- ]phase|2pc|quorum|anillo|token ring|'
    r'eleccion de lider|leader election|algoritmo de eleccion|reloj logico|'
    r'logical clock|reloj vectorial|sincronizacion de relojes|clock synchronization|'
    r'\bntp\b|cristian|bully|maekawa|garcia molina|garcía molina|ricart|agrawala|'
    r'servidor central|\beleccion(?:es)?\b|\belección(?:es)?\b|'
    r'inconsistencia|inconsistency|obsolet|stale read|lectura obsoleta|causal|'
    r'corte consistente|cortes consistentes|diagrama de eventos|'
    r'valores (?:de |toman )?[a-z],? [a-z]|funcion f|función f|evaluar (?:los )?predicados|predicados globales',
    re.I,
)


def main():
    import shutil
    from datetime import datetime, timezone

    data = json.load(open(ROOT / 'app/data/exams.json', encoding='utf-8'))
    ssdd = [e for e in data['exams'] if e.get('subject') == 'ssdd']

    decks_out = []
    for deck, title_es in DECKS:
        pages = pdf_pages(deck)
        deck_slides = []
        for i, text in enumerate(pages, 1):
            deck_slides.append({'page': i, 'title': slide_title(text, i)})
        decks_out.append({
            'id': deck,
            'title': title_es,
            'file': f'temario/ssdd/{deck}.pdf',
            'pages': len(pages),
            'slides': deck_slides,
        })

    questions = {}
    mapped = 0
    supported = 0
    deck_hits = Counter()
    for exam in ssdd:
        for q in exam.get('questions', []):
            slides_for_q, topic = score_question(q)
            key = f"{exam['id']}::{q['id']}"
            questions[key] = {
                'topic': topic,
                'slides': slides_for_q,
            }
            if slides_for_q:
                mapped += 1
                deck_hits[topic or slides_for_q[0]['deck']] += 1
            else:
                supported += 1

    output = {
        'generatedAt': datetime.now(timezone.utc).isoformat(),
        'decks': decks_out,
        'questions': questions,
    }
    out_path = ROOT / 'app/data/ssdd_temario.json'
    out_path.write_text(json.dumps(output, ensure_ascii=False, indent=2), encoding='utf-8')

    # Copia los PDFs para que la app sea autónoma al desplegarse.
    for deck, _ in DECKS:
        src = ROOT / 'temario/ssdd' / f'{deck}.pdf'
        dst = ROOT / 'app/temario/ssdd' / f'{deck}.pdf'
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dst)

    print(f'Temario: {len(decks_out)} temas, {sum(d["pages"] for d in decks_out)} diapositivas')
    print(f'Preguntas SSDD: {len(questions)} · con sugerencias: {mapped} · sin sugerencias: {supported}')
    print('Sugerencias por tema:', dict(deck_hits))
    print(f'Escrito: {out_path}')


if __name__ == '__main__':
    main()
