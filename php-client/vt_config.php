<?php
/*******************************************************************************
 * VT Client Configuration
 *------------------------------------------------------------------------------
 * This file contains configuration details for the PHP VT Client. These should
 * match the configuration details of the VT Server.
 *------------------------------------------------------------------------------
 * Author:
 *  Etienne Gaudrain <etienne.gaudrain@cnrs.fr>, 2020-03-31
 ******************************************************************************/

$VT_CONFIG = array();
$VT_CONFIG['address'] = ['127.0.0.1', 1996];
$VT_CONFIG['vt-cache-path'] = "/var/cache/vt_server";
$VT_CONFIG['vt-cache-url']  = "vt_server_audio";

?>
