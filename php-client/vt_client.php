<?php
/*******************************************************************************
 * VT Client
 *------------------------------------------------------------------------------
 * This is a PHP client for the VT server.
 * This client serves as relay: it receives a JSON request, pass it to the
 * VT Server, then serve the response or the generated sound file.
 *------------------------------------------------------------------------------
 * Author:
 *  Etienne Gaudrain <etienne.gaudrain@cnrs.fr>, 2020-03-31
 ******************************************************************************/

// In safemode, make sure max_execution_time is set adequatly

require('vt_config.php');

function vt_client_handle_request($request)
{
    // The $request is a JSON encoded object. We are not checking it here, so the
    // authentication, etc... has to be performed somewhere else.

    // Is the request valid? No need to send it to VT if it is obviously invalid
    if(!array_key_exists('action', $request))
    {
        echo json_encode(array("out"=>"error", "details"=>"The request needs to have an 'action' key."));
        ob_flush();
        return;
    }

    // Is it the type of request that requires path conversion, i.e., is a file returned?
    if($request['action']=='process' and (!array_key_exists('mode', $request) or $request['mode']!='hash'))
        $do_path_conversion = TRUE;
    else
        $do_path_conversion = FALSE;

    global $VT_CONFIG;

    // Creating the socket
    $socket = socket_create(AF_INET, SOCK_STREAM, SOL_TCP);
    if($socket === false)
    {
        echo json_encode(array('out'=>'error', 'details'=>'Socket could not be created: '.socket_strerror(socket_last_error())))."\n";
        ob_flush();
        return;
    }
    // We only have 5s to do the processing... if you want do heavy computations,
    // make sure to use the 'async' mode for your VT request.
    socket_set_option($socket, SOL_SOCKET, SO_RCVTIMEO, ["sec"=>5, "usec"=>0]);

    // Connecting to VT...
    $result = socket_connect($socket, $VT_CONFIG['address'][0], $VT_CONFIG['address'][1]);
    if($result === false)
    {
        echo json_encode(array('out'=>'error', 'details'=>'Could not connect to server: ($result) '.socket_strerror(socket_last_error($socket))))."\n";
        ob_flush();
        socket_close($socket);
        return;
    }

    // Sending the query
    $req = json_encode($request, JSON_NUMERIC_CHECK)."\n";
    if(socket_write($socket, $req, strlen($req))===false)
    {
        echo json_encode(array('out'=>'error', 'details'=>'Could not send to server: '.socket_strerror(socket_last_error($socket))))."\n";
        ob_flush();
        socket_close($socket);
        return;
    }

    // Reading the response
    $resp = socket_read($socket, 2048);
    socket_close($socket);

    if($do_path_conversion)
    {
        try {

            $resp_a = json_decode($resp, TRUE);
            if($resp_a['out'] == 'ok')
            {
                // Not super safe to use string subsitution... might be better to actually parse the path...
                //$resp_a['details'] = $_SERVER['SERVER_NAME']."/".str_replace($VT_CONFIG['vt-cache-path'], $VT_CONFIG['vt-cache-url'], $resp_a['details']);
                $resp_a['details'] = "/".str_replace($VT_CONFIG['vt-cache-path'], $VT_CONFIG['vt-cache-url'], $resp_a['details']);
                $resp = json_encode($resp_a, JSON_NUMERIC_CHECK)."\n";
            }

        } catch( Error | Exception $e ) {
            // Well, we actually do nothing here, if it is not proper JSON, we let the
            // client deal with it.
            error_log("Something uncanny happened. This should have been some JSON, but it's not or something...: ".$resp);
        }
    }

    echo $resp;
    ob_flush();
}

?>
